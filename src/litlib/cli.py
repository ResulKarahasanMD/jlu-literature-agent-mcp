"""litlib CLI: ortam koruması, görev kuyruğu ve aşama çalıştırma giriş noktası."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

from litlib import __version__
from litlib.config import (
    ensure_dirs,
    ensure_runtime_env,
    ensure_storage_path,
    on_d_drive,
    paths,
    require_d_drive,
)
from litlib.logging_setup import sanitize, sanitize_payload, setup_logging
from litlib.models import TaskState, normalize_doi
from litlib.state import State

STAGES = ("fetch-metadata", "oa", "inst", "verify", "proposal", "import")


def _human_gb(nbytes: float) -> str:
    return f"{nbytes / 1e9:.1f} GB"


def _check_drive(path: Path) -> tuple[str, bool]:
    enforced = require_d_drive()
    ok = on_d_drive(path) if enforced else True
    suffix = "" if ok else "  (LITLIB_REQUIRE_D_DRIVE karşılanmadı)"
    return (f"{'OK ' if ok else 'FAIL'} {path}{suffix}", ok)


def cmd_doctor(args: argparse.Namespace) -> int:
    ensure_dirs(paths)
    print(f"litlib {__version__}  doctor")
    print("-" * 64)
    checks: list[tuple[str, bool]] = []
    for label, p in [
        ("project root", paths.project_root),
        ("venv", paths.venv),
        ("sqlite state", paths.sqlite_dir),
        ("staging downloads", paths.staging_downloads),
        ("staging supplements", paths.staging_supplements),
        ("output", paths.output),
        ("logs", paths.logs),
        ("runtime tmp", paths.tmp),
        ("runtime cache", paths.cache),
        ("models", paths.models),
        ("chrome profile", paths.chrome_profile),
        ("chrome cache", paths.chrome_cache),
        ("chrome downloads", paths.chrome_downloads),
    ]:
        text, ok = _check_drive(p)
        print(f"[{label:>18}] {text}")
        checks.append((label, ok))

    print("-" * 64)
    for env, target in paths.env_map.items():
        actual = os.environ.get(env, "<unset>")
        ok = actual == target
        print(f"[env {env:>18}] expected={target} actual={actual} {'OK' if ok else 'MISMATCH'}")
        checks.append((f"env:{env}", ok))

    email = os.environ.get("LITLIB_EMAIL", "")
    email_ok = bool(email and "@" in email and not email.endswith(".invalid"))
    print(f"[env {'LITLIB_EMAIL':>18}] {'OK <configured>' if email_ok else 'MISSING'}")
    checks.append(("env:LITLIB_EMAIL", email_ok))

    if args.storage:
        print("-" * 64)
        for drive in ("C", "D", "E"):
            try:
                usage = shutil.disk_usage(f"{drive}:\\")
                print(f"[disk {drive}:] used={_human_gb(usage.used)} free={_human_gb(usage.free)}")
            except Exception:
                print(f"[disk {drive}:] N/A")

    failed = [c for c in checks if not c[1]]
    print("-" * 64)
    if failed:
        print(f"FAIL: {len(failed)} kontrol D sürücüsü kısıtını geçemedi:")
        for label, _ in failed:
            print(f"  - {label}")
        return 1
    print("PASS: tüm D sürücüsü kısıtları geçti")
    return 0


def _read_input_file(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"giriş dosyası yok: {path}")
    if p.suffix.lower() == ".csv":
        with p.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise SystemExit(f"CSV'de başlık satırı yok: {path}")
            fields = {name.lower().strip(): name for name in reader.fieldnames if name}
            input_columns = [fields[name] for name in ("doi", "pmid", "pmcid", "arxiv", "title") if name in fields]
            if not input_columns:
                raise SystemExit(f"CSV'de tanınan giriş sütunu yok (doi/pmid/pmcid/arxiv/title): {path}")
            lines: list[str] = []
            for row in reader:
                for column in input_columns:
                    value = (row.get(column) or "").strip()
                    if value:
                        lines.append(value)
                        break
            return lines
    return p.read_text(encoding="utf-8-sig").splitlines()


def cmd_queue_add(args: argparse.Namespace) -> int:
    if args.file:
        lines = _read_input_file(args.file)
    else:
        lines = args.inputs
    if not lines:
        print("hiç DOI/PMID/PMCID/arXiv/başlık girişi verilmedi")
        return 2
    st = State()
    added, skipped = st.queue_add(lines, source=args.source)
    print(f"eklenen görev: {added}, yinelendiği için atlanan: {skipped}")
    st.close()
    return 0


def cmd_queue_recover(args: argparse.Namespace) -> int:
    st = State()
    try:
        recovered, skipped = st.recover_incomplete(
            include_failed=args.failed, include_paused=args.paused)
    finally:
        st.close()
    print(f"kurtarılan görev: {recovered}, deneme sınırı nedeniyle atlanan: {skipped}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    st = State()
    counts = st.state_counts()
    if counts:
        print("Görev istatistikleri:")
        for state, c in sorted(counts.items()):
            print(f"  {state:<20} {c}")
    else:
        print("Görev istatistikleri: (boş)")
    if args.verbose:
        for t in st.list_tasks():
            safe_error = sanitize(t.get("last_error") or "")
            safe_input = sanitize(t.get("raw_input") or "")
            error = f" | {safe_error[:120]}" if safe_error else ""
            print(f"  #{t['id']} {t['state']:<20} {safe_input[:80]}{error}")
    if args.attempts:
        attempts = st.get_route_attempts(args.attempts)
        if not attempts:
            print(f"görev #{args.attempts} için rota denemesi kaydı yok")
        for attempt in attempts:
            error = sanitize(attempt.get("error") or "")
            url = sanitize(attempt.get("url") or "")
            detail = f" | {error[:160]}" if error else ""
            size = f" | {attempt['size_bytes']}B" if attempt.get("size_bytes") else ""
            print(f"  {attempt['id']} {attempt['route']:<20} {attempt['outcome']:<10} {url}{size}{detail}")
    if args.disk:
        for drive in ("C", "D", "E"):
            try:
                u = shutil.disk_usage(f"{drive}:\\")
                print(f"[disk {drive}:] free={_human_gb(u.free)}")
            except Exception:
                pass
    st.close()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    import asyncio

    from litlib.pipeline import run_metadata, run_oa

    exit_code = 0
    st = State()
    try:
        if args.stage == "fetch-metadata":
            result = asyncio.run(run_metadata(st, limit=args.limit))
            print(f"fetch-metadata: {result}")
            if not result.get("processed") or result.get("failed"):
                exit_code = 1
        elif args.stage == "oa":
            result = asyncio.run(run_oa(st, limit=args.limit))
            print(f"oa: {result}")
            if not result.get("processed") or result.get("failed"):
                exit_code = 1
        elif args.stage == "inst":
            from litlib.inst import run_inst

            result = asyncio.run(run_inst(st, limit=args.limit,
                                          access_mode=args.access_mode))
            print(f"inst: {result}")
            if (not result.get("processed") or result.get("failed")
                    or result.get("paused") or result.get("paywalled")):
                exit_code = 1
        elif args.stage == "verify":
            from litlib.verify import verify_downloads

            results = verify_downloads(st)
            for r in results:
                mark = "OK " if r["ok"] else "FAIL"
                print(f"  [{mark}] #{r['task_id']} {r['doi']} {r['detail']}")
            print(f"verify: {sum(1 for r in results if r['ok'])}/{len(results)} geçti")
            if not results or any(not r["ok"] for r in results):
                exit_code = 1
        elif args.stage == "proposal":
            print("`litlib proposal` kullanın; run alt komutu proposal çalıştırmaz")
            exit_code = 2
        elif args.stage == "import":
            print("`litlib import --lookup` kullanın; run alt komutu import çalıştırmaz")
            exit_code = 2
    finally:
        st.close()
    return exit_code


async def _prepare_doi_task(doi: str) -> None:
    """Tek DOI indirmesi için kuyrukta bir görev ve çözümlenmiş metadata olmasını sağlar."""
    import httpx

    from litlib.metadata import fetch_metadata

    st = State()
    try:
        work = st.find_work_by_doi(doi)
        if work is None:
            added, _ = st.queue_add([doi], source="download")
            if added != 1:
                raise RuntimeError(f"DOI için görev oluşturulamadı: {doi}")
            work = st.find_work_by_doi(doi)
        if work is None:
            raise RuntimeError(f"görev oluşturulduktan sonra DOI hâlâ bulunamıyor: {doi}")
        task = st.get_task_for_work(work.work_id)
        if not task:
            raise RuntimeError(f"work {work.work_id} için görev kaydı yok")
        if work.title:
            return
        state = TaskState(task["state"])
        if state is TaskState.FAILED:
            st.set_state(task["id"], TaskState.QUEUED)
            state = TaskState.QUEUED
        if state is TaskState.QUEUED:
            st.set_state(task["id"], TaskState.METADATA_FETCH)
            state = TaskState.METADATA_FETCH
        async with httpx.AsyncClient(timeout=30.0) as client:
            resolved = await fetch_metadata(client, work)
        if not resolved.title:
            if state is TaskState.METADATA_FETCH:
                st.set_state(task["id"], TaskState.FAILED, error="tek makale indirmesinden önce metadata çözümlenemedi")
            raise RuntimeError(f"DOI metadata'sı çözümlenemedi: {doi}")
        st.update_work(resolved)
        if state is TaskState.METADATA_FETCH:
            st.set_state(task["id"], TaskState.DEDUPED)
    finally:
        st.close()


def cmd_download(args: argparse.Namespace) -> int:
    """DOI ile ana metni indirir ve görev veritabanına otomatik kaydeder (indirme + otomatik eşitleme)."""
    import asyncio

    from litlib.config import paths
    from litlib.inst_login import download_doi_and_register
    from litlib.pdf import validate_pdf_for_work

    doi = normalize_doi(args.doi)
    dest = Path(args.output) if args.output else paths.staging_downloads / f"{doi.replace('/', '_')}.pdf"
    ensure_storage_path(dest)
    if dest.exists() and not args.overwrite:
        print(f"hedef dosya zaten var, üzerine yazılmadı: {dest} (gerekirse açıkça --overwrite kullanın)")
        return 2
    asyncio.run(_prepare_doi_task(doi))
    info = asyncio.run(download_doi_and_register(doi, dest))
    pages, chars = validate_pdf_for_work(dest, doi)
    print(json.dumps({"path": str(dest), "pages": pages, "text_chars": chars, **info},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_inst(args: argparse.Namespace) -> int:
    """inst alt komutları: open/tokens/set-cred/check-cred/login."""
    from litlib.inst import cmd_open, cmd_register_token, cmd_tokens

    if args.inst_cmd == "open":
        return cmd_open("https://vpn.jlu.edu.cn" if args.vpn else "about:blank")
    if args.inst_cmd == "tokens":
        return cmd_tokens()
    if args.inst_cmd == "register-token":
        return cmd_register_token(args.domain)
    if args.inst_cmd == "close":
        import asyncio

        from litlib.chrome_cdp import close_browser
        try:
            asyncio.run(close_browser())
        except TimeoutError:
            print("özel tarayıcı çalışmıyor")
            return 0
        print("özel tarayıcı kapatıldı")
        return 0
    if args.inst_cmd == "set-cred":
        return cmd_set_cred()
    if args.inst_cmd == "check-cred":
        from litlib.creds import load_institution_cred
        cred = load_institution_cred()
        if cred:
            print("kurum kimlik bilgisi kayıtlı")
        else:
            print("kurum kimlik bilgisi kayıtlı değil. `litlib inst set-cred` çalıştırın")
        return 0 if cred else 1
    if args.inst_cmd == "login":
        import litlib.inst_login as inst_login
        from litlib.config import paths
        if os.environ.get("LITLIB_EXPORT_SESSION_COOKIES", "0").lower() in {"1", "true", "yes"}:
            inst_login.SESSION_COOKIES_FILE = paths.sqlite_dir / "session_cookies.bin"
        import asyncio
        url = args.url
        host_hint = args.host or ""
        result = asyncio.run(inst_login.auto_login(url, host_hint))
        print(json.dumps(sanitize_payload(result), ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    print("inst alt komutu eksik. Kullanılabilir: open, close, tokens, set-cred, check-cred, login <url>")
    return 2


def cmd_cnki(args: argparse.Namespace) -> int:
    import asyncio

    from litlib.cnki import (
        CNKIError,
        CNKIHumanRequired,
        download_cnki_campus,
        login_cnki_carsi,
        open_cnki_campus,
        search_cnki_campus,
    )

    try:
        if args.cnki_cmd == "open":
            url = asyncio.run(open_cnki_campus())
            print(f"CNKI kampüs ağı girişi açıldı: {url}")
            return 0
        if args.cnki_cmd == "search":
            results = asyncio.run(search_cnki_campus(args.query, args.limit))
            payload = sanitize_payload([result.__dict__ for result in results])
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.cnki_cmd == "download":
            dest = Path(args.output)
            ensure_storage_path(dest)
            if dest.exists() and not args.overwrite:
                print(f"hedef dosya zaten var, üzerine yazılmadı: {dest} (gerekirse açıkça --overwrite kullanın)")
                return 2
            info = asyncio.run(download_cnki_campus(args.url, dest))
            payload = sanitize_payload({"path": str(dest), **info})
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            if dest.exists():
                _record_cnki_experience(dest, args.url)
            return 0
        if args.cnki_cmd == "login-carsi":
            result = asyncio.run(login_cnki_carsi())
            print(json.dumps(sanitize_payload(result), ensure_ascii=False, indent=2))
            return 0 if result.get("ok") else 1
    except CNKIHumanRequired as e:
        print(f"HUMAN_REQUIRED: {e}")
        return 3
    except CNKIError as e:
        print(f"CNKI_ERROR: {e}")
        return 1
    print("cnki alt komutu eksik. Kullanılabilir: open, search, download, login-carsi")
    return 2


def _record_cnki_experience(dest: Path, article_url: str) -> None:
    """CNKI indirmesi başarılı olup dosya gerçekten varsa kişisel deneyimi kaydeder (kanonik profillerin üzerine yazmaz)."""
    try:
        from litlib import experience

        kind = dest.suffix.lstrip(".").lower()
        experience.record_success(
            domain="cnki.net",
            route=f"cnki-{kind}" if kind in ("pdf", "caj") else "cnki-download",
            url_pattern=article_url.split("?", 1)[0],
        )
    except Exception:
        pass


def cmd_set_cred() -> int:
    """Kurumun birleşik kimlik doğrulama hesap parolasını etkileşimli olarak kaydeder (Windows Kimlik Bilgisi Yöneticisi)."""
    import getpass

    from litlib.creds import save_institution_cred

    print("Jilin Üniversitesi birleşik kimlik doğrulama bilgisi kaydedilecek (Windows Kimlik Bilgisi Yöneticisi, sistem düzeyinde şifreli)")
    try:
        username = input("Hesap (JLU e-postası/personel no/öğrenci no): ").strip()
        if not username:
            print("hesap boş olamaz")
            return 2
        password = getpass.getpass("Parola (ekranda görünmez): ")
        if not password:
            print("parola boş olamaz")
            return 2
        confirm = getpass.getpass("Parolayı tekrar girin: ")
        if password != confirm:
            print("iki giriş aynı değil")
            return 2
    except (EOFError, KeyboardInterrupt):
        print("\niptal edildi")
        return 130
    save_institution_cred(username, password)
    print("kaydedildi. Doğrulamak için `litlib inst check-cred`, otomatik giriş için `litlib inst login <url>` çalıştırın.")
    return 0


def _work_ids_from_doi_file(st: State, path: str) -> set[str]:
    """CSV'nin doi sütunundan DOI kümesini çıkarır, work_id'lere eşler."""
    import csv

    do = set()
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            doi = (row.get("doi") or "").strip()
            if doi:
                do.add(doi.lower())
    ids = set()
    for doi in do:
        row = st._conn.execute("SELECT work_id FROM works WHERE doi=?", (doi,)).fetchone()
        if row:
            ids.add(row["work_id"])
    return ids


def cmd_proposal(args: argparse.Namespace) -> int:
    from litlib.importer import build_proposal

    st = State()
    try:
        work_ids = _work_ids_from_doi_file(st, args.doi_file) if args.doi_file else None
        ris, manifest = build_proposal(st, work_ids=work_ids)
        print(f"RIS:      {ris}")
        print(f"Manifest: {manifest}")
    finally:
        st.close()
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Görev veritabanındaki indirilmiş PDF'leri doğrular (varlık/SHA-256/içerik); salt-okur kontrol, durumu değiştirmez."""
    from litlib.verify import verify_downloads

    st = State()
    try:
        task_ids = None
        if args.task:
            task_ids = [int(x) for x in args.task.split(",") if x.strip().isdigit()]
        results = verify_downloads(st, task_ids=task_ids)
        ok = 0
        for r in results:
            if r["ok"]:
                ok += 1
            print(f"  [{'OK ' if r['ok'] else 'FAIL'}] #{r['task_id']} {r['doi']} {r['detail']}")
        print(f"verify: {ok}/{len(results)} geçti")
        return 0 if results and ok == len(results) else 1
    finally:
        st.close()


def cmd_review(args: argparse.Namespace) -> int:
    """Öneri incelemesini onaylar: PROPOSAL_GENERATED → USER_REVIEWED."""
    from litlib.models import TaskState

    st = State()
    try:
        work_ids = _work_ids_from_doi_file(st, args.doi_file) if args.doi_file else None
        n = 0
        for t in st.list_tasks(limit=1000):
            if t["state"] != TaskState.PROPOSAL_GENERATED.value:
                continue
            if work_ids is not None and t["work_id"] not in work_ids:
                continue
            st.mark_reviewed(t["id"])
            n += 1
        print(f"{n} makale incelendi olarak işaretlendi")
    finally:
        st.close()
    return 0 if n else 1


def cmd_import(args: argparse.Namespace) -> int:
    """Zotero içe aktarma onayı: USER_REVIEWED → IMPORTED (zotero_map'e kaydedilir)."""
    from datetime import datetime

    from litlib.models import TaskState

    if not args.lookup:
        print("IMPORTED işareti reddedildi: --lookup ile Zotero'ya bağlanıp item key ve PDF ekini doğrulamak gerekir")
        return 2
    st = State()
    zot = None
    try:
        batch = args.batch or datetime.now().strftime("%Y%m%d_%H%M%S")
        work_ids = _work_ids_from_doi_file(st, args.doi_file) if args.doi_file else None
        try:
            from litlib.zotero_api import ZoteroReadOnly
            zot = ZoteroReadOnly()
            zot.list_collections()
        except Exception as exc:
            print(f"Zotero Local API kullanılamıyor, hiçbir içe aktarma durumu değiştirilmedi: {exc}")
            return 1
        n = 0
        failed = 0
        for t in st.list_tasks(limit=1000):
            if t["state"] != TaskState.USER_REVIEWED.value:
                continue
            if work_ids is not None and t["work_id"] not in work_ids:
                continue
            work = st.get_work(t["work_id"])
            if not work:
                print(f"  [FAIL] task #{t['id']} work kaydı yok")
                failed += 1
                continue
            try:
                matches = zot.find_exact_items(work)
                if len(matches) != 1:
                    raise ValueError(f"Zotero'da tam eşleşme sayısı: {len(matches)}")
                item = matches[0]
                attachment = zot.resolve_pdf(item)
                if not attachment:
                    raise ValueError("Zotero öğesinde okunabilir PDF eki yok")
                key = item.get("key")
                st.mark_imported(t["work_id"], key, batch)
            except Exception as exc:
                print(f"  [FAIL] task #{t['id']} {work.doi or work.title}: {exc}")
                failed += 1
                continue
            n += 1
        print(f"{n} makale doğrulanıp IMPORTED işaretlendi, {failed} başarısız (parti {batch})")
    finally:
        if zot is not None:
            zot.close()
        st.close()
    return 0 if n and not failed else 1


def cmd_mcp(args: argparse.Namespace) -> int:
    from litlib.mcp_server import main as mcp_main

    print("salt-okur MCP sunucusu başlatılıyor (Zotero çalışıyor olmalı)...", file=sys.stderr)
    mcp_main()
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    """Kişisel deneyim kütüphanesi: görüntüle/ekle/sil/dışa aktar (yerel, kanonik profilleri etkilemez)."""
    from litlib import experience

    if args.learn_cmd == "list":
        experiences = experience.load_experiences()
        if not experiences:
            print("Kişisel deneyim kütüphanesi boş. Yeni bir site başarıyla çözülünce otomatik kaydedilir,")
            print("ya da `litlib learn add --domain <alan-adı> --route <rota> --note <açıklama>` ile elle eklenebilir.")
            return 0
        hits = ([e for e in experiences if _domain_filter(args.domain)(e)]
                if args.domain else experiences)
        if not hits:
            print(f"`{args.domain}` ile eşleşen deneyim yok")
            return 0
        for e in hits:
            tag = f"  [{e.get('source')}] {e.get('domain')} <- {e.get('route')}"
            if e.get("doi_prefix"):
                tag += f"  ({e['doi_prefix']})"
            print(tag)
            if e.get("url_pattern"):
                print(f"    URL: {e.get('url_pattern')}")
            if e.get("notes"):
                print(f"    note: {e.get('notes')}")
            print(f"    success={int(e.get('success_count') or 0)}  first={e.get('first_seen')}"
                  + (f"  last={e.get('last_success')}" if e.get("last_success") else ""))
        return 0
    if args.learn_cmd == "add":
        try:
            entry = experience.add_manual(
                domain=args.domain, route=args.route, notes=args.note,
                url_pattern=args.url_pattern or "", doi_prefix=args.doi_prefix or "")
        except ValueError as exc:
            print(f"add başarısız: {exc}")
            return 2
        print(f"deneyim kaydedildi: {entry['domain']} <- {entry['route']} (id={entry['id']})")
        return 0
    if args.learn_cmd == "remove":
        ok = experience.remove_experience(args.id)
        print(f"deneyim silindi: {args.id}" if ok else f"deneyim bulunamadı: {args.id}")
        return 0 if ok else 1
    if args.learn_cmd == "export":
        print(experience.render_markdown())
        return 0
    print("learn alt komutu eksik")
    return 2


def _domain_filter(domain: str):
    """Verilen alan adıyla eşleşen deneyim filtresini döndürür (alt alan adı/ana alan adı iki yönlü eşleşme)."""
    from litlib.experience import _domain_key

    key = _domain_key(domain)

    def _matches(entry: dict) -> bool:
        d = _domain_key(entry.get("domain", ""))
        return bool(d and (d == key or d.endswith("." + key) or key.endswith("." + d)))
    return _matches


def _write_json_output(payload: dict | list, output: str) -> None:
    if not output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    target = Path(output)
    ensure_storage_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON: {target}")


def cmd_uniprot(args: argparse.Namespace) -> int:
    import asyncio

    import httpx

    from litlib.uniprot import fetch_entry

    async def fetch_all() -> list[dict]:
        async with httpx.AsyncClient(timeout=60) as client:
            return [await fetch_entry(client, accession) for accession in args.accessions]

    try:
        entries = asyncio.run(fetch_all())
    except (httpx.HTTPError, ValueError) as exc:
        print(f"UniProt alınamadı: {exc}")
        return 1
    payload = entries[0] if len(entries) == 1 else entries
    _write_json_output(payload, args.output)
    if args.queue:
        st = State()
        try:
            identifiers = []
            for entry in entries:
                identifiers.extend(
                    reference[key]
                    for reference in entry["references"]
                    for key in ("doi", "pmid", "pmcid")
                    if reference.get(key)
                )
            added, skipped = st.queue_add(identifiers, source="uniprot")
            print(f"bağlantılı literatür kuyruğa eklendi: {added}, yinelendiği için atlanan: {skipped}")
        finally:
            st.close()
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    from litlib.evidence import scan_pdf_evidence

    try:
        result = scan_pdf_evidence(args.pdf)
    except Exception as exc:
        print(f"kanıt taraması başarısız: {exc}")
        return 1
    _write_json_output(result, args.output)
    return 0


def cmd_supplement(args: argparse.Namespace) -> int:
    import asyncio

    import httpx

    from litlib.supplements import (
        SupplementCandidate,
        discover_supplements_from_page,
        download_supplement,
    )

    if args.supplement_cmd == "discover":
        async def discover() -> list[dict]:
            async with httpx.AsyncClient(timeout=60) as client:
                candidates = await discover_supplements_from_page(client, args.article_url)
            return [candidate.safe_dict() for candidate in candidates]

        try:
            _write_json_output(asyncio.run(discover()), args.output)
        except Exception as exc:
            print(f"ek materyal bulunamadı: {exc}")
            return 1
        return 0
    if args.supplement_cmd == "download":
        candidate = SupplementCandidate(args.url, args.label, args.media_type)
        output_path = Path(args.output) if args.output else (
            paths.staging_supplements / Path(urlparse(args.url).path).name
        )
        if not output_path.name:
            print("ek dosya adı URL'den çıkarılamadı, --output verin")
            return 2

        async def download() -> dict:
            async with httpx.AsyncClient(timeout=120) as client:
                return await download_supplement(
                    client, candidate, output_path, parent_doi=args.doi,
                    overwrite=args.overwrite,
                )

        try:
            _write_json_output(asyncio.run(download()), "")
        except Exception as exc:
            print(f"ek materyal indirilemedi: {exc}")
            return 1
        return 0
    print("supplement alt komutu eksik")
    return 2


def cmd_cellulase(args: argparse.Namespace) -> int:
    from litlib.cellulase import (
        load_jsonl,
        normalize_records,
        select_maxima,
        validate_jsonl,
        write_jsonl,
    )

    if args.cellulase_cmd == "validate":
        result = validate_jsonl(args.input)
        _write_json_output(result, args.output)
        return 0 if result["valid"] else 1
    if args.cellulase_cmd == "maxima":
        try:
            records = normalize_records(load_jsonl(args.input))
            maxima = select_maxima(records)
            write_jsonl(args.output, maxima)
            print(f"maksimum kayıtları: {len(maxima)} -> {args.output}")
            return 0
        except Exception as exc:
            print(f"maksimum seçimi başarısız: {exc}")
            return 1
    print("cellulase alt komutu eksik")
    return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="litlib", description="Kişisel literatür kütüphanesi sistemi")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("doctor", help="ortam ve D sürücüsü koruması")
    d.add_argument("--storage", action="store_true", help="disk kapasitesi raporunu da göster")

    q = sub.add_parser("queue", help="görev kuyruğu")
    qsub = q.add_subparsers(dest="queue_cmd")
    add = qsub.add_parser("add", help="görev ekle (DOI/PMID/başlık; dosyadan ya da doğrudan)")
    add.add_argument("--file", "-f", help="giriş dosyası (satır başına bir kayıt; CSV'de ilk sütun desteklenir)")
    add.add_argument("--source", default="manual", help="kaynak etiketi")
    add.add_argument("inputs", nargs="*", help="doğrudan girilen kayıtlar")
    recover = qsub.add_parser("recover", help="çökmeden kalan ara durumdaki görevleri kurtar")
    recover.add_argument("--failed", action="store_true", help="FAILED görevleri de yeniden kuyruğa al")
    recover.add_argument("--paused", action="store_true", help="RATE_LIMITED/HUMAN_REQUIRED görevleri de yeniden kuyruğa al")

    s = sub.add_parser("status", help="görev durumu")
    s.add_argument("--disk", action="store_true", help="disk kapasitesi")
    s.add_argument("--verbose", "-v", action="store_true", help="görev ayrıntılarını listele")
    s.add_argument("--attempts", type=int, help="belirtilen görevin rota rota indirme denetimini listele")

    v = sub.add_parser("verify", help="indirilmiş PDF'leri doğrula (varlık/SHA-256/içerik)")
    v.add_argument("--task", default="", help="yalnız belirtilen görev id'lerini doğrula (virgülle ayrılmış)")

    r = sub.add_parser("run", help="aşama çalıştır")
    r.add_argument("--stage", choices=STAGES, required=True)
    r.add_argument("--limit", type=int, default=100,
                   help="bu partinin üst sınırı; kurum aşamasında kod 10'u aşmaya izin vermez")
    r.add_argument("--access-mode", choices=("auto", "campus", "offcampus"),
                   default="auto", help="kurum aşamasının rota sırası (varsayılan auto)")

    dl = sub.add_parser("download", help="DOI ile ana metni indir ve görev veritabanına otomatik kaydet")
    dl.add_argument("doi", help="DOI, örn. 10.1002/pro.4785")
    dl.add_argument("--output", "-o", default="", help="PDF çıktı yolu (varsayılan staging/downloads)")
    dl.add_argument("--overwrite", action="store_true", help="var olan hedef PDF'in üzerine yazmaya açıkça izin ver")

    i = sub.add_parser("inst", help="kurum kanalı (WebVPN ağ geçidi + özel Chrome + kurum girişi)")
    isub = i.add_subparsers(dest="inst_cmd")
    open_cmd = isub.add_parser("open", help="özel Chrome'u başlat")
    open_cmd.add_argument("--vpn", action="store_true", help="WebVPN giriş sayfasını da aç")
    isub.add_parser("tokens", help="kayıtlı ağ geçidi alan adı token'larını listele")
    register_token = isub.add_parser("register-token", help="geçerli WebVPN sekmesinden yayıncı token'ı kaydet")
    register_token.add_argument("domain", help="özgün yayıncı alan adı, örn. nature.com")
    isub.add_parser("close", help="özel Chrome'u kapat")
    isub.add_parser("set-cred", help="kurumun birleşik kimlik doğrulama hesap parolasını kaydet (Kimlik Bilgisi Yöneticisi)")
    isub.add_parser("check-cred", help="kurum kimlik bilgisinin kayıtlı olduğunu doğrula")
    login = isub.add_parser("login", help="bir kurum girişini otomatik tamamla")
    login.add_argument("url", help="yayıncı sitesi URL'i (örn. https://www.cell.com/)")
    login.add_argument("--host", default="", help="geri dönülmesi beklenen host (isteğe bağlı)")

    c = sub.add_parser("cnki", help="CNKI kampüs ağı arama/indirme ve CARSI girişi")
    csub = c.add_subparsers(dest="cnki_cmd")
    csub.add_parser("open", help="CNKI kampüs ağı arama sayfasını aç; güvenlik doğrulaması elle tamamlanmalı")
    cnki_search = csub.add_parser("search", help="CNKI kampüs ağı oturumunda ara")
    cnki_search.add_argument("query", help="arama terimi")
    cnki_search.add_argument("--limit", type=int, default=10, help="en fazla döndürülecek kayıt sayısı")
    cnki_download = csub.add_parser("download", help="bir CNKI kaydının PDF'ini indir")
    cnki_download.add_argument("url", help="CNKI makale ayrıntı sayfası URL'i")
    cnki_download.add_argument("--output", required=True, help="PDF çıktı yolu")
    cnki_download.add_argument("--overwrite", action="store_true", help="var olan dosyanın üzerine yazmaya açıkça izin ver")
    csub.add_parser("login-carsi", help="kampüs dışı CNKI CARSI/kurum girişi (kampüs dışında henüz doğrulanmadı)")

    sub.add_parser("mcp", help="salt-okur MCP sunucusunu başlat")

    pr = sub.add_parser("proposal", help="içe aktarma önerisi üret (RIS + liste)")
    pr.add_argument("--doi-file", "-f", default="", help="yalnız bu CSV'deki DOI'leri dahil et (doi sütunu)")
    rv = sub.add_parser("review", help="öneri incelemesini onayla (PROPOSAL_GENERATED → USER_REVIEWED)")
    rv.add_argument("--doi-file", "-f", default="", help="yalnız bu CSV'deki DOI'leri işle (doi sütunu)")
    im = sub.add_parser("import", help="Zotero içe aktarma onayı (USER_REVIEWED → IMPORTED)")
    im.add_argument("--batch", default="", help="içe aktarma parti adı (varsayılan: geçerli zaman damgası)")
    im.add_argument("--doi-file", "-f", default="", help="yalnız bu CSV'deki DOI'leri işle (doi sütunu)")
    im.add_argument("--lookup", action="store_true", help="Zotero Local API üzerinden DOI ile item key'i doldurmayı dene")

    lr = sub.add_parser("learn", help="kişisel deneyim kütüphanesi (yerel, kendini geliştiren)")
    lrsub = lr.add_subparsers(dest="learn_cmd")
    learn_list = lrsub.add_parser("list", help="kişisel deneyimleri listele (--domain ile süzülebilir)")
    learn_list.add_argument("--domain", default="", help="süzülecek alan adı")
    lrsub.add_parser("export", help="Markdown özeti dışa aktar (Agent okuyabilir)")
    learn_add = lrsub.add_parser("add", help="elle deneyim ekle")
    learn_add.add_argument("--domain", required=True, help="site alan adı, örn. pubs.acs.org")
    learn_add.add_argument("--route", required=True, help="rota adı, örn. direct-httpx / cnki-pdf")
    learn_add.add_argument("--note", required=True, help="deneyim açıklaması (insan gözleminin sonucu)")
    learn_add.add_argument("--url-pattern", default="", help="yeniden kullanılabilir URL kalıbı (otomatik maskelenir)")
    learn_add.add_argument("--doi-prefix", default="", help="DOI öneki, örn. 10.1021")
    learn_remove = lrsub.add_parser("remove", help="id ile bir deneyimi sil")
    learn_remove.add_argument("id", help="deneyim id'si (learn list'te görünür)")

    up = sub.add_parser("uniprot", help="UniProt kaydını, dizisini ve bağlantılı literatürü al")
    up.add_argument("accessions", nargs="+", help="UniProt accession; birden fazla verilebilir")
    up.add_argument("--output", "-o", default="", help="JSON çıktı yolu; verilmezse ekrana yazdırılır")
    up.add_argument("--queue", action="store_true", help="kayda bağlı DOI/PMID/PMCID'leri görev kuyruğuna ekle")

    ev = sub.add_parser("evidence", help="makale PDF'inde hedef alanları ve ek materyal/şekil ipuçlarını tara")
    evsub = ev.add_subparsers(dest="evidence_cmd")
    evscan = evsub.add_parser("scan", help="bir PDF'i tara")
    evscan.add_argument("pdf", help="ana metin PDF yolu")
    evscan.add_argument("--output", "-o", default="", help="JSON çıktı yolu; verilmezse ekrana yazdırılır")

    sp = sub.add_parser("supplement", help="ek materyal/Source Data bul ya da indir")
    spsub = sp.add_subparsers(dest="supplement_cmd")
    spdiscover = spsub.add_parser("discover", help="makale sayfasındaki ek materyal bağlantılarını tara")
    spdiscover.add_argument("article_url", help="makale sayfası URL'i")
    spdiscover.add_argument("--output", "-o", default="", help="JSON çıktı yolu; verilmezse ekrana yazdırılır")
    spdownload = spsub.add_parser("download", help="bir ek dosyayı indirip doğrula")
    spdownload.add_argument("url", help="ek dosya URL'i")
    spdownload.add_argument("--output", "-o", default="", help="yerel çıktı yolu (varsayılan staging/supplements)")
    spdownload.add_argument("--doi", default="", help="ana makalenin DOI'si")
    spdownload.add_argument("--label", default="supplement", help="dosya etiketi")
    spdownload.add_argument("--media-type", default="", help="HTTP media type")
    spdownload.add_argument("--overwrite", action="store_true", help="üzerine yazmaya açıkça izin ver")

    ce = sub.add_parser("cellulase", help="selülaz yapılandırılmış kayıt aracı")
    cesub = ce.add_subparsers(dest="cellulase_cmd")
    cevalidate = cesub.add_parser("validate", help="JSONL kayıtlarını ve eksik alan durumlarını doğrula")
    cevalidate.add_argument("input", help="CellulaseMeasurement JSONL")
    cevalidate.add_argument("--output", "-o", default="", help="JSON çıktı yolu; verilmezse ekrana yazdırılır")
    cemax = cesub.add_parser("maxima", help="yapı/substrat/metrik/birim grubuna göre en yüksek gözlenen değeri seç")
    cemax.add_argument("input", help="CellulaseMeasurement JSONL")
    cemax.add_argument("--output", "-o", required=True, help="maksimum değerler için JSONL çıktı yolu")
    return p


def main(argv: list[str] | None = None) -> int:
    ensure_runtime_env()
    args = build_parser().parse_args(argv)
    if args.cmd != "mcp":
        ensure_dirs(paths)
        setup_logging()
    if args.cmd == "doctor":
        return cmd_doctor(args)
    if args.cmd == "queue":
        if args.queue_cmd == "add":
            return cmd_queue_add(args)
        if args.queue_cmd == "recover":
            return cmd_queue_recover(args)
        print("queue alt komutu eksik")
        return 2
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "verify":
        return cmd_verify(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "inst":
        return cmd_inst(args)
    if args.cmd == "cnki":
        return cmd_cnki(args)
    if args.cmd == "download":
        return cmd_download(args)
    if args.cmd == "mcp":
        return cmd_mcp(args)
    if args.cmd == "proposal":
        return cmd_proposal(args)
    if args.cmd == "review":
        return cmd_review(args)
    if args.cmd == "import":
        return cmd_import(args)
    if args.cmd == "learn":
        return cmd_learn(args)
    if args.cmd == "uniprot":
        return cmd_uniprot(args)
    if args.cmd == "evidence":
        if args.evidence_cmd == "scan":
            return cmd_evidence(args)
        print("evidence alt komutu eksik")
        return 2
    if args.cmd == "supplement":
        return cmd_supplement(args)
    if args.cmd == "cellulase":
        return cmd_cellulase(args)
    print("komut eksik. Kullanılabilir: doctor, queue add, status, run, download, proposal, review, import, mcp")
    return 2


if __name__ == "__main__":
    sys.exit(main())
