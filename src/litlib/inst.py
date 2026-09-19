"""机构通道阶段：当前网络直连 → 可选 WebVPN → 机构登录 → 校验。

工作流：
  1. litlib inst open          启动专用 Chrome
  2. litlib run --stage inst   校内/校外按任务独立降级
  3. 如需 WebVPN，使用 inst open --vpn 与 inst register-token

网瑞达 wengine 网关改写格式：
  https://vpn.jlu.edu.cn/https/{host_token}/{path}
  token 需从门户资源点击中提取（用户点一次即可登记到 token 缓存）。
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
    """构造网关改写 URL；path 不含域名。"""
    token = tokens.get(domain)
    if not token:
        return None
    return f"{GATEWAY}/https/{token}/{path}"


def extract_gateway_token(url: str) -> str:
    """从 WebVPN 改写 URL 提取 host token。"""
    parsed = urlparse(url)
    if parsed.hostname != "vpn.jlu.edu.cn":
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "https":
        return parts[1]
    return ""


def cmd_register_token(domain: str) -> int:
    """从当前浏览器 WebVPN 标签页登记一个 publisher token。"""
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
        print("未找到 WebVPN 改写标签页。请先从 WebVPN 门户打开目标站点。")
        return 1
    key = domain.lower().removeprefix("www.")
    tokens = load_tokens()
    tokens[key] = token
    save_tokens(tokens)
    print(f"已登记 {key}: <redacted>（长度 {len(token)}）")
    return 0


def doi_to_publisher(doi: str) -> tuple[str, str] | None:
    """DOI → (publisher 域名, 文章路径)。仅支持已知出版社格式。"""
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
    """机构阶段成功下载后自动记录个人经验（本地 learn 库，不影响 canonical）。"""
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
    """启动专用 Chrome；按需打开 WebVPN 或其他站点。"""
    print("启动专用 Chrome（CDP 127.0.0.1:9222）...")
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
    session.proc = None  # 后续由 `litlib inst close` 通过 CDP 关闭
    if "vpn.jlu.edu.cn" in url:
        print("请在浏览器中手动登录 WebVPN；完成后即可运行机构阶段。")
    else:
        print("专用浏览器已就绪。需要 WebVPN 时运行 `litlib inst open --vpn`。")
    print("注意：本命令退出后 Chrome 会保持运行，批处理结束后才关闭。")
    return 0


def cmd_tokens() -> int:
    """列出已登记网关 token。"""
    tokens = load_tokens()
    if not tokens:
        print("尚无 token。登录 WebVPN 后，在门户/数据库导航中点击目标站点一次即可登记。")
        return 0
    for domain, token in tokens.items():
        print(f"{domain}: <present>（长度 {len(token)}）")
    return 0


async def get_vpn_cookies() -> dict[str, str]:
    """从 CDP 连接的 Chrome 取 vpn.jlu.edu.cn 的 cookie（需已登录）。"""
    try:
        await chrome_cdp.wait_for_cdp(timeout=10)
    except TimeoutError:
        raise RuntimeError("CDP 无响应，请先 `litlib inst open` 启动浏览器") from None
    async with httpx.AsyncClient(timeout=15) as client:
        pages = (await client.get(f"http://{chrome_cdp.CDP_HOST}:{chrome_cdp.CDP_PORT}/json/list", timeout=10)).json()
        page = next((p for p in pages if p.get("type") == "page"), None)
        if not page:
            raise RuntimeError("无可用页面")
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
    """httpx 直连网关 URL 下载 PDF，返回元数据；失败抛异常。"""
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
            raise PDFError(f"非 PDF（content-type={ctype}, size={size}）")
        os.replace(tmp, dest)
        return {"size": size, "content_type": ctype}
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


async def download_via_browser(
    tokens: dict[str, str], domain: str, path: str, dest: Path
) -> dict:
    """CDP 浏览器 fetch 网关 URL（Cloudflare 等站点 httpx 直连 403 时回退）。"""
    base = gateway_url(tokens, domain, "")
    if not base:
        raise PDFError(f"缺少 {domain} 网关 token")
    target = gateway_url(tokens, domain, path)
    ws = await chrome_cdp.create_tab_navigate(base, timeout=30)
    if not ws:
        raise PDFError("无法创建浏览器网关标签页")
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
        raise ValueError(f"未知 access_mode: {access_mode}")
    limit = min(max(1, limit), BATCH_LIMIT)
    tasks = st.list_tasks(state=TaskState.REQUIRES_INST, limit=limit)
    stats = {"processed": 0, "ok": 0, "failed": 0, "paused": 0, "paywalled": 0}
    if not tasks:
        print("无 REQUIRES_INST 任务")
        return stats
    print(f"本批 {len(tasks)} 篇（并发 1，间隔 8–15s）")
    tokens = load_tokens()
    print(f"已登记 token: {list(tokens.keys()) or '无'}")
    cookies: dict[str, str] | None = None
    # BVU (GlobalProtect VPN) only uses the direct routes; JLU gateway/IdP login are skipped.
    jlu_routes = not bvu.is_active()
    async with httpx.AsyncClient(timeout=120) as client:
        if not jlu_routes:
            ok, evidence = await bvu.vpn_preflight(client)
            if not ok:
                stats["paused"] = len(tasks)
                print(f"HUMAN_REQUIRED: {evidence}")
                print("  GlobalProtect'e bağlanıp tekrar çalıştırın; görevler REQUIRES_INST'te kaldı")
                return stats
            print(f"BVU erişimi doğrulandı: {evidence}")
        for t in tasks:
            work = st.get_work(t["work_id"])
            stats["processed"] += 1
            if not work or not work.doi:
                st.set_state(t["id"], TaskState.REQUIRES_INST, error="机构渠道需要 DOI")
                stats["paused"] += 1
                print(f"[task {t['id']}] 无 DOI，需人工处理")
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
                    print(f"[task {t['id']}] 恢复既有 PDF: {n_pages} 页 / {n_chars} 字符")
                except Exception as exc:
                    st.set_state(
                        t["id"], TaskState.REQUIRES_INST,
                        error=f"HUMAN_REQUIRED: existing output requires review: {exc}",
                    )
                    stats["paused"] += 1
                    print(f"[task {t['id']}] 目标 PDF 已存在且未通过恢复校验，未覆盖")
                continue
            if not st.begin_attempt(t["id"]):
                stats["paused"] += 1
                print(f"[task {t['id']}] 已达到最大尝试次数，跳过")
                continue
            mapped = doi_to_publisher(work.doi)
            domain, path = mapped or ("", "")
            print(f"[task {t['id']}] {work.doi} -> {domain or 'DOI 实际落地站'}")
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

                # 快速路线：已知 PDF URL 先走普通流式下载，校内 IP 下通常直接命中。
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
                            r"\b429\b|too many requests|站点限流", str(e), re.I))
                        paywalled_route = bool(re.search(r"PAYWALLED|需购买|付费墙", str(e), re.I))
                        human_checkpoint = bool(re.search(
                            r"HUMAN[_ -]?REQUIRED|人机验证|captcha|turnstile", str(e), re.I))
                        dest.unlink(missing_ok=True)

                # 通用路线：当前网络/浏览器会话直连。校内 IP 与已登录会话都在此命中。
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
                            r"429|too many requests|站点限流", str(e), re.I))
                        paywalled_route = bool(re.search(r"PAYWALLED|需购买|付费墙", str(e), re.I))
                        human_checkpoint = bool(re.search(
                            r"HUMAN[_ -]?REQUIRED|人机验证|captcha|turnstile", str(e), re.I))
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
                            r"\b429\b|too many requests|站点限流", str(e), re.I))
                        paywalled_route = bool(re.search(r"PAYWALLED|需购买|付费墙", str(e), re.I))
                        human_checkpoint = bool(re.search(
                            r"HUMAN[_ -]?REQUIRED|人机验证|captcha|turnstile", str(e), re.I))
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
                            r"\b429\b|too many requests|站点限流", str(e), re.I))
                        paywalled_route = bool(re.search(r"PAYWALLED|需购买|付费墙", str(e), re.I))
                        human_checkpoint = bool(re.search(
                            r"HUMAN[_ -]?REQUIRED|人机验证|captcha|turnstile", str(e), re.I))
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
                            r"\b429\b|too many requests|站点限流", str(e), re.I))
                        paywalled_route = bool(re.search(r"PAYWALLED|需购买|付费墙", str(e), re.I))
                        human_checkpoint = bool(re.search(
                            r"HUMAN[_ -]?REQUIRED|人机验证|captcha|turnstile", str(e), re.I))
                        dest.unlink(missing_ok=True)
                        return None

                # 可选路线：已有 WebVPN ticket + 当前 publisher token 时才尝试，不再阻断后续登录。
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
                        raise PDFError("PAYWALLED: publisher 明确无授权 PDF")
                    if human_checkpoint:
                        raise PDFError("HUMAN_REQUIRED: 等待用户完成可见验证/同意页面")
                    if rate_limited:
                        raise PDFError("RATE_LIMITED: publisher 当前限制专用浏览器访问")
                    raise PDFError("所有机构访问路线均失败")

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
                print(f"  [OK] {n_pages} 页, {dest.stat().st_size / 1e6:.1f} MB")
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
                    r"HUMAN[_ -]?REQUIRED|人机验证|captcha|turnstile", detail, re.I))
                paywalled = bool(re.search(
                    r"PAYWALLED|buy protocol|purchase-only|需购买|付费墙", detail, re.I))
                rate_limited = rate_limited or bool(re.search(
                    r"RATE_LIMITED|\b429\b|too many requests|站点限流", detail, re.I))
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
                    print("  批次已暂停；完成人工 checkpoint 或等待冷却后再 recover --paused")
                    break
            delay = random.uniform(*DELAY)
            print(f"  等待 {delay:.0f}s ...")
            time.sleep(delay)
    return stats
