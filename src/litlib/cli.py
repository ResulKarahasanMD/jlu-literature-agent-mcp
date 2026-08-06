"""litlib CLI：环境守卫、任务队列与阶段执行入口。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from pathlib import Path

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
    suffix = "" if ok else "  (未满足 LITLIB_REQUIRE_D_DRIVE)"
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
        print(f"FAIL: {len(failed)} 项未通过 D 盘约束:")
        for label, _ in failed:
            print(f"  - {label}")
        return 1
    print("PASS: 全部 D 盘约束通过")
    return 0


def _read_input_file(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"输入文件不存在: {path}")
    if p.suffix.lower() == ".csv":
        with p.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise SystemExit(f"CSV 缺少表头: {path}")
            fields = {name.lower().strip(): name for name in reader.fieldnames if name}
            input_columns = [fields[name] for name in ("doi", "pmid", "pmcid", "arxiv", "title") if name in fields]
            if not input_columns:
                raise SystemExit(f"CSV 缺少可识别输入列（doi/pmid/pmcid/arxiv/title）: {path}")
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
        print("未提供任何 DOI/PMID/PMCID/arXiv/标题输入")
        return 2
    st = State()
    added, skipped = st.queue_add(lines, source=args.source)
    print(f"新增任务: {added}, 因重复跳过: {skipped}")
    st.close()
    return 0


def cmd_queue_recover(args: argparse.Namespace) -> int:
    st = State()
    try:
        recovered, skipped = st.recover_incomplete(
            include_failed=args.failed, include_paused=args.paused)
    finally:
        st.close()
    print(f"恢复任务: {recovered}, 达重试上限跳过: {skipped}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    st = State()
    counts = st.state_counts()
    if counts:
        print("任务统计:")
        for state, c in sorted(counts.items()):
            print(f"  {state:<20} {c}")
    else:
        print("任务统计: (空)")
    if args.verbose:
        for t in st.list_tasks():
            safe_error = sanitize(t.get("last_error") or "")
            safe_input = sanitize(t.get("raw_input") or "")
            error = f" | {safe_error[:120]}" if safe_error else ""
            print(f"  #{t['id']} {t['state']:<20} {safe_input[:80]}{error}")
    if args.attempts:
        attempts = st.get_route_attempts(args.attempts)
        if not attempts:
            print(f"任务 #{args.attempts} 无路线尝试记录")
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
            print(f"verify: {sum(1 for r in results if r['ok'])}/{len(results)} 通过")
            if not results or any(not r["ok"] for r in results):
                exit_code = 1
        elif args.stage == "proposal":
            print("请使用 `litlib proposal`；run 子命令不执行 proposal")
            exit_code = 2
        elif args.stage == "import":
            print("请使用 `litlib import --lookup`；run 子命令不执行 import")
            exit_code = 2
    finally:
        st.close()
    return exit_code


async def _prepare_doi_task(doi: str) -> None:
    """Ensure a single-DOI download has a queued task and resolved metadata."""
    import httpx

    from litlib.metadata import fetch_metadata

    st = State()
    try:
        work = st.find_work_by_doi(doi)
        if work is None:
            added, _ = st.queue_add([doi], source="download")
            if added != 1:
                raise RuntimeError(f"无法为 DOI 建立任务: {doi}")
            work = st.find_work_by_doi(doi)
        if work is None:
            raise RuntimeError(f"任务建立后仍找不到 DOI: {doi}")
        task = st.get_task_for_work(work.work_id)
        if not task:
            raise RuntimeError(f"work {work.work_id} 缺少任务记录")
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
                st.set_state(task["id"], TaskState.FAILED, error="单篇下载前未解析出元数据")
            raise RuntimeError(f"未解析出 DOI 元数据: {doi}")
        st.update_work(resolved)
        if state is TaskState.METADATA_FETCH:
            st.set_state(task["id"], TaskState.DEDUPED)
    finally:
        st.close()


def cmd_download(args: argparse.Namespace) -> int:
    """按 DOI 下载正文并自动登记到任务库（下载 + 自动同步）。"""
    import asyncio

    from litlib.config import paths
    from litlib.inst_login import download_doi_and_register
    from litlib.pdf import validate_pdf_for_work

    doi = normalize_doi(args.doi)
    dest = Path(args.output) if args.output else paths.staging_downloads / f"{doi.replace('/', '_')}.pdf"
    ensure_storage_path(dest)
    if dest.exists() and not args.overwrite:
        print(f"目标文件已存在，未覆盖: {dest}（需要时显式使用 --overwrite）")
        return 2
    asyncio.run(_prepare_doi_task(doi))
    info = asyncio.run(download_doi_and_register(doi, dest))
    pages, chars = validate_pdf_for_work(dest, doi)
    print(json.dumps({"path": str(dest), "pages": pages, "text_chars": chars, **info},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_inst(args: argparse.Namespace) -> int:
    """inst 子命令：open/tokens/set-cred/check-cred/login。"""
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
            print("专用浏览器未运行")
            return 0
        print("专用浏览器已关闭")
        return 0
    if args.inst_cmd == "set-cred":
        return cmd_set_cred()
    if args.inst_cmd == "check-cred":
        from litlib.creds import load_institution_cred
        cred = load_institution_cred()
        if cred:
            print("已保存机构凭证")
        else:
            print("未保存机构凭证。请运行 `litlib inst set-cred`")
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
    print("缺少 inst 子命令。可用: open, close, tokens, set-cred, check-cred, login <url>")
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
            print(f"CNKI 校园网入口已打开: {url}")
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
                print(f"目标文件已存在，未覆盖: {dest}（需要时显式使用 --overwrite）")
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
    print("缺少 cnki 子命令。可用: open, search, download, login-carsi")
    return 2


def _record_cnki_experience(dest: Path, article_url: str) -> None:
    """CNKI 下载成功且文件真实存在后，记录个人经验（不覆盖 canonical 档案）。"""
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
    """交互式保存机构统一认证账号密码（Windows 凭据管理器）。"""
    import getpass

    from litlib.creds import save_institution_cred

    print("将保存吉林大学统一身份认证凭证（Windows 凭据管理器，系统级加密）")
    try:
        username = input("账号（吉大邮箱/工号/学号）: ").strip()
        if not username:
            print("账号不能为空")
            return 2
        password = getpass.getpass("密码（输入不回显）: ")
        if not password:
            print("密码不能为空")
            return 2
        confirm = getpass.getpass("再次输入密码: ")
        if password != confirm:
            print("两次输入不一致")
            return 2
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return 130
    save_institution_cred(username, password)
    print("已保存。运行 `litlib inst check-cred` 确认，`litlib inst login <url>` 自动登录。")
    return 0


def _work_ids_from_doi_file(st: State, path: str) -> set[str]:
    """从 CSV 的 doi 列解析 DOI 集合，映射到 work_id。"""
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
    """校验任务库已下载 PDF（存在性/SHA-256/内容），只读检查不改状态。"""
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
        print(f"verify: {ok}/{len(results)} 通过")
        return 0 if results and ok == len(results) else 1
    finally:
        st.close()


def cmd_review(args: argparse.Namespace) -> int:
    """提案审阅确认：PROPOSAL_GENERATED → USER_REVIEWED。"""
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
        print(f"已标记审阅完成 {n} 篇")
    finally:
        st.close()
    return 0 if n else 1


def cmd_import(args: argparse.Namespace) -> int:
    """Zotero 导入确认：USER_REVIEWED → IMPORTED（记录 zotero_map）。"""
    from datetime import datetime

    from litlib.models import TaskState

    if not args.lookup:
        print("拒绝标记 IMPORTED：必须使用 --lookup 连接 Zotero 并验证 item key 与 PDF 附件")
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
            print(f"Zotero Local API 不可用，未修改任何导入状态: {exc}")
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
                print(f"  [FAIL] task #{t['id']} 缺少 work")
                failed += 1
                continue
            try:
                matches = zot.find_exact_items(work)
                if len(matches) != 1:
                    raise ValueError(f"Zotero 精确匹配数为 {len(matches)}")
                item = matches[0]
                attachment = zot.resolve_pdf(item)
                if not attachment:
                    raise ValueError("Zotero 条目没有可读取的 PDF 附件")
                key = item.get("key")
                st.mark_imported(t["work_id"], key, batch)
            except Exception as exc:
                print(f"  [FAIL] task #{t['id']} {work.doi or work.title}: {exc}")
                failed += 1
                continue
            n += 1
        print(f"已验证并标记 IMPORTED {n} 篇，失败 {failed} 篇（批次 {batch}）")
    finally:
        if zot is not None:
            zot.close()
        st.close()
    return 0 if n and not failed else 1


def cmd_mcp(args: argparse.Namespace) -> int:
    from litlib.mcp_server import main as mcp_main

    print("启动只读 MCP server（Zotero 需运行）...", file=sys.stderr)
    mcp_main()
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    """个人经验库：查看/添加/删除/导出（本地自进化，不影响 canonical 档案）。"""
    from litlib import experience

    if args.learn_cmd == "list":
        experiences = experience.load_experiences()
        if not experiences:
            print("个人经验库为空。成功解决新站点后会自动记录，")
            print("也可用 `litlib learn add --domain <域名> --route <路线> --note <说明>` 手动补充。")
            return 0
        hits = ([e for e in experiences if _domain_filter(args.domain)(e)]
                if args.domain else experiences)
        if not hits:
            print(f"没有与 `{args.domain}` 匹配的经验")
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
            print(f"add 失败: {exc}")
            return 2
        print(f"已记录经验: {entry['domain']} <- {entry['route']} (id={entry['id']})")
        return 0
    if args.learn_cmd == "remove":
        ok = experience.remove_experience(args.id)
        print(f"已删除经验 {args.id}" if ok else f"未找到经验 {args.id}")
        return 0 if ok else 1
    if args.learn_cmd == "export":
        print(experience.render_markdown())
        return 0
    print("缺少 learn 子命令")
    return 2


def _domain_filter(domain: str):
    """返回与给定域名匹配的经验过滤器（子域/主域双向匹配）。"""
    from litlib.experience import _domain_key

    key = _domain_key(domain)

    def _matches(entry: dict) -> bool:
        d = _domain_key(entry.get("domain", ""))
        return bool(d and (d == key or d.endswith("." + key) or key.endswith("." + d)))
    return _matches


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="litlib", description="个人文献库系统")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("doctor", help="环境与 D 盘守卫")
    d.add_argument("--storage", action="store_true", help="附带磁盘容量报告")

    q = sub.add_parser("queue", help="任务队列")
    qsub = q.add_subparsers(dest="queue_cmd")
    add = qsub.add_parser("add", help="添加任务（DOI/PMID/标题，文件或直接输入）")
    add.add_argument("--file", "-f", help="输入文件（每行一个，支持 CSV 首列）")
    add.add_argument("--source", default="manual", help="来源标记")
    add.add_argument("inputs", nargs="*", help="直接输入条目")
    recover = qsub.add_parser("recover", help="恢复崩溃遗留的中间状态任务")
    recover.add_argument("--failed", action="store_true", help="同时重新排队 FAILED 任务")
    recover.add_argument("--paused", action="store_true", help="同时重新排队 RATE_LIMITED/HUMAN_REQUIRED 任务")

    s = sub.add_parser("status", help="任务状态")
    s.add_argument("--disk", action="store_true", help="磁盘容量")
    s.add_argument("--verbose", "-v", action="store_true", help="列出任务明细")
    s.add_argument("--attempts", type=int, help="列出指定任务的逐路线下载审计")

    v = sub.add_parser("verify", help="校验已下载 PDF（存在性/SHA-256/内容）")
    v.add_argument("--task", default="", help="仅校验指定任务 id（逗号分隔）")

    r = sub.add_parser("run", help="执行阶段")
    r.add_argument("--stage", choices=STAGES, required=True)
    r.add_argument("--limit", type=int, default=100,
                   help="本批处理上限；机构阶段代码强制不超过 10")
    r.add_argument("--access-mode", choices=("auto", "campus", "offcampus"),
                   default="auto", help="机构阶段路线顺序（默认 auto）")

    dl = sub.add_parser("download", help="按 DOI 下载正文并自动登记到任务库")
    dl.add_argument("doi", help="DOI，如 10.1002/pro.4785")
    dl.add_argument("--output", "-o", default="", help="PDF 输出路径（默认 staging/downloads）")
    dl.add_argument("--overwrite", action="store_true", help="显式允许覆盖已存在的目标 PDF")

    i = sub.add_parser("inst", help="机构通道（WebVPN 网关 + 专用 Chrome + 机构登录）")
    isub = i.add_subparsers(dest="inst_cmd")
    open_cmd = isub.add_parser("open", help="启动专用 Chrome")
    open_cmd.add_argument("--vpn", action="store_true", help="同时打开 WebVPN 登录页")
    isub.add_parser("tokens", help="列出已登记的网关域名 token")
    register_token = isub.add_parser("register-token", help="从当前 WebVPN 标签页登记 publisher token")
    register_token.add_argument("domain", help="原始 publisher 域名，如 nature.com")
    isub.add_parser("close", help="关闭专用 Chrome")
    isub.add_parser("set-cred", help="保存机构统一认证账号密码（凭据管理器）")
    isub.add_parser("check-cred", help="确认机构凭证已保存")
    login = isub.add_parser("login", help="自动完成一次机构登录")
    login.add_argument("url", help="出版社站点 URL（如 https://www.cell.com/）")
    login.add_argument("--host", default="", help="期望回跳的主机（可选）")

    c = sub.add_parser("cnki", help="CNKI 校园网检索下载与 CARSI 登录")
    csub = c.add_subparsers(dest="cnki_cmd")
    csub.add_parser("open", help="打开 CNKI 校园网检索页；安全验证需人工完成")
    cnki_search = csub.add_parser("search", help="检索 CNKI 校园网会话")
    cnki_search.add_argument("query", help="检索词")
    cnki_search.add_argument("--limit", type=int, default=10, help="最多返回条数")
    cnki_download = csub.add_parser("download", help="下载一个 CNKI 条目 PDF")
    cnki_download.add_argument("url", help="CNKI 文献详情页 URL")
    cnki_download.add_argument("--output", required=True, help="PDF 输出路径")
    cnki_download.add_argument("--overwrite", action="store_true", help="显式允许覆盖已存在文件")
    csub.add_parser("login-carsi", help="校外 CNKI CARSI/机构登录（待非校园网验证）")

    sub.add_parser("mcp", help="启动只读 MCP server")

    pr = sub.add_parser("proposal", help="生成导入提案（RIS + 清单）")
    pr.add_argument("--doi-file", "-f", default="", help="仅包含该 CSV 中的 DOI（doi 列）")
    rv = sub.add_parser("review", help="提案审阅确认（PROPOSAL_GENERATED → USER_REVIEWED）")
    rv.add_argument("--doi-file", "-f", default="", help="仅处理该 CSV 中的 DOI（doi 列）")
    im = sub.add_parser("import", help="Zotero 导入确认（USER_REVIEWED → IMPORTED）")
    im.add_argument("--batch", default="", help="导入批次名（默认当前时间戳）")
    im.add_argument("--doi-file", "-f", default="", help="仅处理该 CSV 中的 DOI（doi 列）")
    im.add_argument("--lookup", action="store_true", help="尝试经 Zotero Local API 按 DOI 回填 item key")

    lr = sub.add_parser("learn", help="个人经验库（本地自进化）")
    lrsub = lr.add_subparsers(dest="learn_cmd")
    learn_list = lrsub.add_parser("list", help="列出个人经验（可用 --domain 过滤）")
    learn_list.add_argument("--domain", default="", help="过滤域名")
    lrsub.add_parser("export", help="导出 Markdown 摘要（Agent 可读）")
    learn_add = lrsub.add_parser("add", help="手动补充经验")
    learn_add.add_argument("--domain", required=True, help="站点域名，如 pubs.acs.org")
    learn_add.add_argument("--route", required=True, help="路线名，如 direct-httpx / cnki-pdf")
    learn_add.add_argument("--note", required=True, help="经验说明（人工观察结论）")
    learn_add.add_argument("--url-pattern", default="", help="可复用的 URL 模式（自动脱敏）")
    learn_add.add_argument("--doi-prefix", default="", help="DOI 前缀，如 10.1021")
    learn_remove = lrsub.add_parser("remove", help="按 id 删除一条经验")
    learn_remove.add_argument("id", help="经验 id（learn list 可见）")
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
        print("缺少 queue 子命令")
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
    print("缺少命令。可用: doctor, queue add, status, run, download, proposal, review, import, mcp")
    return 2


if __name__ == "__main__":
    sys.exit(main())
