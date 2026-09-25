"""Kurum kanalı aşaması: geçerli ağdan doğrudan bağlantı → isteğe bağlı WebVPN → kurum girişi → doğrulama.

İş akışı:
  1. litlib inst open          özel Chrome'u başlatır
  2. litlib run --stage inst   kampüs içi/dışı; her görev için ayrı ayrı geri düşer
  3. WebVPN gerekirse inst open --vpn ve inst register-token kullanılır

Wangruida wengine ağ geçidinin yeniden yazma biçimi:
  https://vpn.jlu.edu.cn/https/{host_token}/{path}
  token portaldaki kaynak tıklamasından çıkarılır (kullanıcının bir kez tıklaması token önbelleğine kaydetmeye yeter).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from litlib import bvu, chrome_cdp
from litlib.config import paths
from litlib.download import download_to_file
from litlib.logging_setup import sanitize, sanitize_payload
from litlib.models import TaskState, sha256_of_file
from litlib.pdf import PDFError, validate_pdf_for_work
from litlib.state import State

logger = logging.getLogger("litlib.inst")

BATCH_LIMIT = 10
DELAY = (8, 15)
GATEWAY = "https://vpn.jlu.edu.cn"
TOKENS_FILE = paths.sqlite_dir / "vpn_tokens.json"
LEGACY_TOKENS_FILE = paths.tmp / "vpn_tokens.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")


def load_tokens() -> dict[str, str]:
    for file in (TOKENS_FILE, LEGACY_TOKENS_FILE):
        try:
            tokens = json.loads(file.read_text(encoding="utf-8"))
            if file == LEGACY_TOKENS_FILE and not TOKENS_FILE.exists():
                save_tokens(tokens)
            return tokens
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return {}


def save_tokens(tokens: dict[str, str]) -> None:
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKENS_FILE.write_text(json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")


def gateway_url(tokens: dict[str, str], domain: str, path: str) -> str | None:
    """Ağ geçidinin yeniden yazdığı URL'i kurar; path alan adı içermez."""
    token = tokens.get(domain)
    if not token:
        return None
    return f"{GATEWAY}/https/{token}/{path}"


def extract_gateway_token(url: str) -> str:
    """WebVPN'in yeniden yazdığı URL'den host token'ını çıkarır."""
    parsed = urlparse(url)
    if parsed.hostname != "vpn.jlu.edu.cn":
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "https":
        return parts[1]
    return ""


def cmd_register_token(domain: str) -> int:
    """Geçerli tarayıcıdaki WebVPN sekmesinden bir yayıncı token'ı kaydeder."""
    async def _register() -> str:
        await chrome_cdp.wait_for_cdp(timeout=10)
        async with httpx.AsyncClient(timeout=15) as client:
            pages = (await client.get(
                f"http://{chrome_cdp.CDP_HOST}:{chrome_cdp.CDP_PORT}/json/list")).json()
        for page in pages:
            token = extract_gateway_token(page.get("url", ""))
            if token:
                return token
        return ""

    token = asyncio.run(_register())
    if not token:
        print("WebVPN ile yeniden yazılmış sekme bulunamadı. Önce hedef siteyi WebVPN portalından açın.")
        return 1
    key = domain.lower().removeprefix("www.")
    tokens = load_tokens()
    tokens[key] = token
    save_tokens(tokens)
    print(f"kaydedildi {key}: <redacted> (uzunluk {len(token)})")
    return 0


def doi_to_publisher(doi: str) -> tuple[str, str] | None:
    """DOI → (yayıncı alan adı, makale yolu). Yalnız bilinen yayıncı biçimleri desteklenir."""
    doi = doi.lower().strip()
    if doi.startswith("10.1038/"):
        return "nature.com", f"articles/{doi[len('10.1038/'):]}.pdf"
    if doi.startswith("10.1126/"):
        return "science.org", f"doi/pdf/{doi}"
    if doi.startswith("10.1007/"):
        return "link.springer.com", f"content/pdf/{doi}.pdf"
    if doi.startswith("10.1002/"):
        return "onlinelibrary.wiley.com", f"doi/pdfdirect/{doi}"
    if doi.startswith("10.1016/j.cell"):
        return "cell.com", ""
    if doi.startswith("10.1016/"):
        return "linkinghub.elsevier.com", ""
    if doi.startswith("10.1093/"):
        return "academic.oup.com", ""
    if doi.startswith("10.1021/"):
        return "pubs.acs.org", ""
    if doi.startswith("10.1039/"):
        return "pubs.rsc.org", ""
    if doi.startswith("10.1146/"):
        return "annualreviews.org", ""
    if doi.startswith("10.1017/"):
        return "cambridge.org", ""
    if doi.startswith("10.1159/"):
        return "karger.com", ""
    if doi.startswith("10.1097/"):
        return "journals.lww.com", ""
    if doi.startswith("10.1080/"):
        return "tandfonline.com", ""
    return None


def _record_inst_experience(domain: str, inst_channel: str, doi: str) -> None:
    """Kurum aşamasında başarılı indirmeden sonra kişisel deneyimi otomatik kaydeder (yerel learn kütüphanesi, kanonik olanı etkilemez)."""
    if not domain:
        return
    try:
        from litlib import experience

        doi_prefix = doi.strip().lower().split("/", 1)[0] if doi else ""
        experience.record_success(
            domain=domain,
            route=inst_channel,
            doi_prefix=doi_prefix,
            url_pattern=f"https://{domain}/",
        )
    except Exception:
        logger.exception("record experience failed for %s", domain)


def cmd_open(url: str = "about:blank") -> int:
    """Özel Chrome'u başlatır; gerekirse WebVPN'i ya da başka bir siteyi açar."""
    print("Özel Chrome başlatılıyor (CDP 127.0.0.1:9222)...")
    session = chrome_cdp.launch_chrome()

    async def _open_vpn() -> None:
        ws = await chrome_cdp.wait_for_cdp(timeout=30)
        print(f"CDP OK: {ws}")
        async with httpx.AsyncClient(timeout=15) as client:
            tab = await chrome_cdp.new_tab(client, url)
            await tab.connect()
            await chrome_cdp.navigate(tab, url)

    try:
        asyncio.run(_open_vpn())
    except Exception:
        session.close()
        raise
    session.proc = None  # sonra `litlib inst close` CDP üzerinden kapatır
    if "vpn.jlu.edu.cn" in url:
        print("Tarayıcıda WebVPN'e elle giriş yapın; bitince kurum aşaması çalıştırılabilir.")
    else:
        print("Özel tarayıcı hazır. WebVPN gerektiğinde `litlib inst open --vpn` çalıştırın.")
    print("Not: bu komut bittikten sonra Chrome çalışmaya devam eder, ancak parti işlemi bitince kapatılır.")
    return 0


def cmd_tokens() -> int:
    """Kayıtlı ağ geçidi token'larını listeler."""
    tokens = load_tokens()
    if not tokens:
        print("Henüz token yok. WebVPN'e girdikten sonra portal/veritabanı menüsünde hedef siteye bir kez tıklamak kaydetmeye yeter.")
        return 0
    for domain, token in tokens.items():
        print(f"{domain}: <present> (uzunluk {len(token)})")
    return 0


async def get_vpn_cookies() -> dict[str, str]:
    """CDP ile bağlı Chrome'dan vpn.jlu.edu.cn çerezini alır (giriş yapılmış olmalı)."""
    try:
        await chrome_cdp.wait_for_cdp(timeout=10)
    except TimeoutError:
        raise RuntimeError("CDP yanıt vermiyor; önce `litlib inst open` ile tarayıcıyı başlatın") from None
    async with httpx.AsyncClient(timeout=15) as client:
        pages = (await client.get(f"http://{chrome_cdp.CDP_HOST}:{chrome_cdp.CDP_PORT}/json/list", timeout=10)).json()
        page = next((p for p in pages if p.get("type") == "page"), None)
        if not page:
            raise RuntimeError("kullanılabilir sayfa yok")
        tab = chrome_cdp.Tab(page["webSocketDebuggerUrl"])
        await tab.connect()
        try:
            await tab.cmd("Network.enable")
            r = await tab.cmd("Network.getCookies", {"urls": [GATEWAY]})
        finally:
            await tab.close()
    return {c["name"]: c["value"] for c in r.get("cookies", [])}


def _ticket_valid(cookies: dict[str, str]) -> bool:
    return any(k.startswith("wengine_vpn_ticket") for k in cookies)


async def download_via_gateway(
    client: httpx.AsyncClient, cookies: dict[str, str], url: str, dest: Path
) -> dict:
    """httpx ile ağ geçidi URL'inden doğrudan PDF indirir, metadata döndürür; başarısızlıkta istisna fırlatır."""
    headers = {"User-Agent": UA, "Accept": "application/pdf,*/*"}
    tmp = dest.with_suffix(".part")
    tmp.unlink(missing_ok=True)
    try:
        async with client.stream("GET", url, headers=headers, cookies=cookies,
                                 follow_redirects=True, timeout=120) as resp:
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "").lower()
            size = 0
            with tmp.open("wb") as f:
                async for chunk in resp.aiter_bytes(1 << 16):
                    f.write(chunk)
                    size += len(chunk)
        with tmp.open("rb") as f:
            magic = f.read(4)
        if magic != b"%PDF":
            raise PDFError(f"PDF değil (content-type={ctype}, size={size})")
        os.replace(tmp, dest)
        return {"size": size, "content_type": ctype}
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


async def download_via_browser(
    tokens: dict[str, str], domain: str, path: str, dest: Path
) -> dict:
    """Ağ geçidi URL'ini CDP tarayıcısında fetch eder (Cloudflare gibi sitelerde httpx doğrudan 403 alınca yedek yol)."""
    base = gateway_url(tokens, domain, "")
    if not base:
        raise PDFError(f"{domain} için ağ geçidi token'ı yok")
    target = gateway_url(tokens, domain, path)
    ws = await chrome_cdp.create_tab_navigate(base, timeout=30)
    if not ws:
        raise PDFError("tarayıcıda ağ geçidi sekmesi oluşturulamadı")
    tab = chrome_cdp.Tab(ws)
    await tab.connect()
    try:
        await asyncio.sleep(4)
        from litlib.inst_login import fetch_pdf_via_browser
        return await fetch_pdf_via_browser(tab, target, dest)
    finally:
        await tab.close_target()


async def run_inst(st: State, limit: int = BATCH_LIMIT,
                   access_mode: str = "auto") -> dict:
    if access_mode not in {"auto", "campus", "offcampus"}:
        raise ValueError(f"bilinmeyen access_mode: {access_mode}")
    limit = min(max(1, limit), BATCH_LIMIT)
    tasks = st.list_tasks(state=TaskState.REQUIRES_INST, limit=limit)
    stats = {"processed": 0, "ok": 0, "failed": 0, "paused": 0, "paywalled": 0}
    if not tasks:
        print("REQUIRES_INST durumunda görev yok")
        return stats
    print(f"bu partide {len(tasks)} makale (eşzamanlılık 1, aralık 8–15 sn)")
    tokens = load_tokens()
    print(f"kayıtlı token: {list(tokens.keys()) or 'yok'}")
    cookies: dict[str, str] | None = None
    # BVU (GlobalProtect VPN) yalnız doğrudan rotaları kullanır; JLU ağ geçidi/IdP girişi atlanır.
    jlu_routes = not bvu.is_active()
    async with httpx.AsyncClient(timeout=120) as client:
        if not jlu_routes:
            ok, evidence = await bvu.vpn_preflight(client)
            if not ok:
                stats["paused"] = len(tasks)
                coded = evidence.startswith(("HUMAN_REQUIRED", "RATE_LIMITED"))
                print(evidence if coded else f"HUMAN_REQUIRED: {evidence}")
                print("  GlobalProtect'e bağlanıp tekrar çalıştırın; görevler REQUIRES_INST'te kaldı")
                return stats
            print(f"BVU erişimi doğrulandı: {evidence}")
        for t in tasks:
            work = st.get_work(t["work_id"])
            stats["processed"] += 1
            if not work or not work.doi:
                st.set_state(t["id"], TaskState.REQUIRES_INST, error="kurum kanalı DOI gerektirir")
                stats["paused"] += 1
                print(f"[task {t['id']}] DOI yok, elle işlem gerekli")
                continue
            dest = paths.staging_downloads / f"{work.work_id}.pdf"
            if dest.exists():
                try:
                    n_pages, n_chars = validate_pdf_for_work(dest, work.doi)
                    sha = sha256_of_file(dest)
                    owner = st.dedupe_owner("sha256", sha)
                    if owner and owner != work.work_id:
                        raise ValueError(f"existing PDF belongs to work {owner}")
                    for state in (
                        TaskState.INST_QUEUED, TaskState.DOWNLOADING,
                        TaskState.VERIFYING,
                    ):
                        st.set_state(t["id"], state)
                    st.add_file(
                        work.work_id, str(dest), sha, dest.stat().st_size,
                        "recovered-existing",
                    )
                    st.set_state(t["id"], TaskState.READY)
                    stats["ok"] += 1
                    print(f"[task {t['id']}] mevcut PDF geri kazanıldı: {n_pages} sayfa / {n_chars} karakter")
                except Exception as exc:
                    st.set_state(
                        t["id"], TaskState.REQUIRES_INST,
                        error=f"HUMAN_REQUIRED: existing output requires review: {exc}",
                    )
                    stats["paused"] += 1
                    print(f"[task {t['id']}] hedef PDF zaten var ve geri kazanım doğrulamasından geçmedi, üzerine yazılmadı")
                continue
            if not st.begin_attempt(t["id"]):
                stats["paused"] += 1
                print(f"[task {t['id']}] azami deneme sayısına ulaşıldı, atlandı")
                continue
            mapped = doi_to_publisher(work.doi)
            domain, path = mapped or ("", "")
            print(f"[task {t['id']}] {work.doi} -> {domain or 'DOI yönlendirmesinin gerçek hedefi'}")
            errors: list[str] = []
            rate_limited = False
            paywalled_route = False
            human_checkpoint = False
            verified_output = False
            try:
                st.set_state(t["id"], TaskState.INST_QUEUED)
                st.set_state(t["id"], TaskState.DOWNLOADING)
                from litlib.inst_login import (
                    download_doi_via_browser,
                    login_and_download_doi,
                    resolve_doi_host,
                )

                async def run_route(route: str, route_url: str, operation) -> dict:
                    route_id = st.start_route_attempt(t["id"], route, route_url)
                    try:
                        result = await operation()
                    except Exception as exc:
                        st.finish_route_attempt(route_id, "FAILED", str(exc))
                        raise
                    st.finish_route_attempt(
                        route_id, "SUCCEEDED", size_bytes=int(result.get("size", 0) or 0))
                    return result

                # Hızlı rota: bilinen PDF URL'i önce normal akışlı indirmeyle denenir; kampüs IP'sinde genellikle doğrudan tutar.
                info = None
                if domain and path:
                    direct_url = f"https://{domain}/{path}"
                    inst_channel = "direct-httpx"
                    try:
                        async def direct_httpx_download() -> dict:
                            _, _, size = await download_to_file(client, direct_url, dest)
                            validate_pdf_for_work(dest, work.doi)
                            return {"size": size, "content_type": "application/pdf", "via": "httpx"}

                        info = await run_route("direct-httpx", direct_url, direct_httpx_download)
                    except Exception as e:
                        errors.append(f"direct-httpx: {e}")
                        rate_limited = bool(re.search(
                            r"\b429\b|too many requests|站点限流|hız sınırı", str(e), re.I))
                        paywalled_route = bool(re.search(r"PAYWALLED|需购买|付费墙|ödeme duvarı", str(e), re.I))
                        human_checkpoint = bool(re.search(
                            r"HUMAN[_ -]?REQUIRED|人机验证|insan doğrulaması|captcha|turnstile", str(e), re.I))
                        dest.unlink(missing_ok=True)

                # Genel rota: geçerli ağ/tarayıcı oturumundan doğrudan bağlantı. Kampüs IP'si de oturum açılmış oturum da burada tutar.
                if info is None and not rate_limited and not paywalled_route and not human_checkpoint:
                    inst_channel = "direct-browser"
                    try:
                        async def direct_browser_download() -> dict:
                            result = await download_doi_via_browser(work.doi, dest)
                            validate_pdf_for_work(dest, work.doi)
                            return result

                        info = await run_route(
                            "direct-browser", f"https://doi.org/{work.doi}",
                            direct_browser_download)
                    except Exception as e:
                        errors.append(f"direct-browser: {e}")
                        rate_limited = bool(re.search(
                            r"429|too many requests|站点限流|hız sınırı", str(e), re.I))
                        paywalled_route = bool(re.search(r"PAYWALLED|需购买|付费墙|ödeme duvarı", str(e), re.I))
                        human_checkpoint = bool(re.search(
                            r"HUMAN[_ -]?REQUIRED|人机验证|insan doğrulaması|captcha|turnstile", str(e), re.I))
                        dest.unlink(missing_ok=True)
                        info = None

                async def try_gateway() -> dict | None:
                    nonlocal cookies, inst_channel, rate_limited, paywalled_route, human_checkpoint
                    if not url:
                        return None
                    if cookies is None:
                        try:
                            cookies = await get_vpn_cookies()
                        except RuntimeError:
                            cookies = {}
                    if not _ticket_valid(cookies):
                        return None
                    inst_channel = "gateway-httpx"
                    try:
                        async def gateway_httpx_download() -> dict:
                            result = await download_via_gateway(client, cookies, url, dest)
                            validate_pdf_for_work(dest, work.doi)
                            return result

                        result = await run_route(
                            "gateway-httpx", url,
                            gateway_httpx_download)
                        return result
                    except Exception as e:
                        errors.append(f"gateway-httpx: {e}")
                        rate_limited = bool(re.search(
                            r"\b429\b|too many requests|站点限流|hız sınırı", str(e), re.I))
                        paywalled_route = bool(re.search(r"PAYWALLED|需购买|付费墙|ödeme duvarı", str(e), re.I))
                        human_checkpoint = bool(re.search(
                            r"HUMAN[_ -]?REQUIRED|人机验证|insan doğrulaması|captcha|turnstile", str(e), re.I))
                        dest.unlink(missing_ok=True)
                        if rate_limited or paywalled_route or human_checkpoint:
                            return None
                    try:
                        inst_channel = "gateway-browser"
                        async def gateway_browser_download() -> dict:
                            result = await download_via_browser(tokens, domain, path, dest)
                            validate_pdf_for_work(dest, work.doi)
                            return result

                        result = await run_route(
                            "gateway-browser", url,
                            gateway_browser_download)
                        return result
                    except Exception as e:
                        errors.append(f"gateway-browser: {e}")
                        rate_limited = bool(re.search(
                            r"\b429\b|too many requests|站点限流|hız sınırı", str(e), re.I))
                        paywalled_route = bool(re.search(r"PAYWALLED|需购买|付费墙|ödeme duvarı", str(e), re.I))
                        human_checkpoint = bool(re.search(
                            r"HUMAN[_ -]?REQUIRED|人机验证|insan doğrulaması|captcha|turnstile", str(e), re.I))
                        dest.unlink(missing_ok=True)
                        return None

                async def try_login() -> dict | None:
                    nonlocal inst_channel, rate_limited, paywalled_route, human_checkpoint
                    inst_channel = "institution-login"
                    resolved_domain = await resolve_doi_host(work.doi)
                    actual_domain = domain if domain == "cell.com" else resolved_domain or domain
                    try:
                        async def institution_login_download() -> dict:
                            result = await login_and_download_doi(work.doi, dest, actual_domain)
                            validate_pdf_for_work(dest, work.doi)
                            return result

                        result = await run_route(
                            "institution-login", f"https://{actual_domain}/",
                            institution_login_download)
                        return result
                    except Exception as e:
                        errors.append(f"institution-login: {e}")
                        rate_limited = bool(re.search(
                            r"\b429\b|too many requests|站点限流|hız sınırı", str(e), re.I))
                        paywalled_route = bool(re.search(r"PAYWALLED|需购买|付费墙|ödeme duvarı", str(e), re.I))
                        human_checkpoint = bool(re.search(
                            r"HUMAN[_ -]?REQUIRED|人机验证|insan doğrulaması|captcha|turnstile", str(e), re.I))
                        dest.unlink(missing_ok=True)
                        return None

                # İsteğe bağlı rota: yalnız WebVPN bileti + geçerli yayıncı token'ı varsa denenir; sonraki girişi artık engellemez.
                url = gateway_url(tokens, domain, path) if domain and path else None
                if (info is None and jlu_routes and access_mode == "offcampus"
                        and not rate_limited and not paywalled_route and not human_checkpoint):
                    info = await try_login()
                if (info is None and jlu_routes and access_mode != "campus"
                        and not rate_limited and not paywalled_route and not human_checkpoint):
                    info = await try_gateway()
                if (info is None and jlu_routes and access_mode != "offcampus"
                        and not rate_limited and not paywalled_route and not human_checkpoint):
                    info = await try_login()
                if info is None:
                    if paywalled_route:
                        raise PDFError("PAYWALLED: yayıncı açıkça yetkili PDF sunmuyor (ödeme duvarı)")
                    if human_checkpoint:
                        raise PDFError("HUMAN_REQUIRED: kullanıcının görünür doğrulama/onay sayfasını tamamlaması bekleniyor")
                    if rate_limited:
                        raise PDFError("RATE_LIMITED: yayıncı şu an özel tarayıcının erişimini sınırlıyor (hız sınırı)")
                    raise PDFError("tüm kurum erişim rotaları başarısız")

                st.set_state(t["id"], TaskState.VERIFYING)
                n_pages, n_chars = validate_pdf_for_work(dest, work.doi)
                verified_output = True
                sha = sha256_of_file(dest)
                work.extra["inst"] = sanitize_payload({
                    "url": f"https://doi.org/{work.doi}", "pages": n_pages,
                    "text_chars": n_chars, "channel": inst_channel,
                    "attempt_errors": errors, **info,
                })
                st.update_work(work)
                st.add_file(work.work_id, str(dest), sha, dest.stat().st_size, inst_channel)
                st.set_state(t["id"], TaskState.READY)
                stats["ok"] += 1
                print(f"  [OK] {n_pages} sayfa, {dest.stat().st_size / 1e6:.1f} MB")
                _record_inst_experience(domain, inst_channel, work.doi)
            except Exception as e:
                if not verified_output:
                    dest.unlink(missing_ok=True)
                detail = sanitize(" | ".join(errors + [str(e)]))[:900]
                work.extra["inst"] = {
                    "url": f"https://doi.org/{work.doi}",
                    "channel": "failed",
                    "attempt_errors": [sanitize(error) for error in errors + [str(e)]],
                }
                st.update_work(work)
                human_required = bool(re.search(
                    r"HUMAN[_ -]?REQUIRED|人机验证|insan doğrulaması|captcha|turnstile", detail, re.I))
                paywalled = bool(re.search(
                    r"PAYWALLED|buy protocol|purchase-only|需购买|付费墙|ödeme duvarı", detail, re.I))
                rate_limited = rate_limited or bool(re.search(
                    r"RATE_LIMITED|\b429\b|too many requests|站点限流|hız sınırı", detail, re.I))
                code = (
                    "PAYWALLED" if paywalled else "HUMAN_REQUIRED" if human_required
                    else "RATE_LIMITED" if rate_limited else "DOWNLOAD_FAILED"
                )
                target_state = (
                    TaskState.PAYWALLED if paywalled
                    else TaskState.HUMAN_REQUIRED if human_required
                    else TaskState.RATE_LIMITED if rate_limited
                    else TaskState.REQUIRES_INST
                )
                st.set_state(t["id"], target_state,
                             error=f"{code}: {detail}")
                if paywalled:
                    stats["paywalled"] += 1
                elif human_required or rate_limited:
                    stats["paused"] += 1
                else:
                    stats["failed"] += 1
                print(f"  [x] {e}")
                if human_required or rate_limited:
                    print("  parti duraklatıldı; insan checkpoint'ini tamamlayın ya da soğuma süresini bekleyip recover --paused çalıştırın")
                    break
            delay = random.uniform(*DELAY)
            print(f"  {delay:.0f} sn bekleniyor ...")
            time.sleep(delay)
    return stats
