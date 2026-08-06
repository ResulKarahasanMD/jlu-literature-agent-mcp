"""下载校验：对任务库已登记文件做存在性/SHA-256/PDF 内容校验（§18 verify）。"""

from __future__ import annotations

from pathlib import Path

from litlib.models import sha256_of_file
from litlib.pdf import validate_pdf_for_work
from litlib.state import State


def verify_task(st: State, task: dict) -> dict:
    """校验单任务已登记文件，返回 {task_id, work_id, doi, ok, detail}。"""
    work = st.get_work(task["work_id"])
    doi = work.doi if work else None
    files = st.get_files(task["work_id"])
    if not files:
        return {"task_id": task["id"], "work_id": task["work_id"], "doi": doi,
                "ok": False, "detail": "无文件记录"}
    path = Path(files[0]["path"])
    if not path.exists() or path.stat().st_size == 0:
        return {"task_id": task["id"], "work_id": task["work_id"], "doi": doi,
                "ok": False, "detail": f"文件缺失或为空: {path}"}
    recorded_sha = files[0].get("sha256")
    if recorded_sha:
        actual = sha256_of_file(path)
        if actual != recorded_sha:
            return {"task_id": task["id"], "work_id": task["work_id"], "doi": doi,
                    "ok": False, "detail": "SHA-256 不匹配（文件被改动）"}
    try:
        pages, chars = validate_pdf_for_work(path, doi)
    except Exception as e:
        return {"task_id": task["id"], "work_id": task["work_id"], "doi": doi,
                "ok": False, "detail": f"PDF 校验失败: {e}"}
    return {"task_id": task["id"], "work_id": task["work_id"], "doi": doi,
            "ok": True, "detail": f"{pages} 页 / {chars} 字符", "size": path.stat().st_size}


def verify_downloads(st: State, task_ids: list[int] | None = None) -> list[dict]:
    """校验全部有文件记录的任务（或指定 task_ids）。"""
    tasks = st.list_tasks(limit=1000)
    if task_ids:
        tasks = [t for t in tasks if t["id"] in task_ids]
    results = []
    for t in tasks:
        if not st.get_files(t["work_id"]):
            continue
        results.append(verify_task(st, t))
    return results
