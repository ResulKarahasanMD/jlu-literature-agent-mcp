"""İndirme doğrulaması: görev veritabanına kayıtlı dosyalar için varlık/SHA-256/PDF içerik kontrolü (§18 verify)."""

from __future__ import annotations

from pathlib import Path

from litlib.models import sha256_of_file
from litlib.pdf import validate_pdf_for_work
from litlib.state import State


def verify_task(st: State, task: dict) -> dict:
    """Tek bir görevin kayıtlı dosyasını doğrular, {task_id, work_id, doi, ok, detail} döndürür."""
    work = st.get_work(task["work_id"])
    doi = work.doi if work else None
    files = st.get_files(task["work_id"])
    if not files:
        return {"task_id": task["id"], "work_id": task["work_id"], "doi": doi,
                "ok": False, "detail": "dosya kaydı yok"}
    path = Path(files[0]["path"])
    if not path.exists() or path.stat().st_size == 0:
        return {"task_id": task["id"], "work_id": task["work_id"], "doi": doi,
                "ok": False, "detail": f"dosya eksik ya da boş: {path}"}
    recorded_sha = files[0].get("sha256")
    if recorded_sha:
        actual = sha256_of_file(path)
        if actual != recorded_sha:
            return {"task_id": task["id"], "work_id": task["work_id"], "doi": doi,
                    "ok": False, "detail": "SHA-256 uyuşmuyor (dosya değiştirilmiş)"}
    try:
        pages, chars = validate_pdf_for_work(path, doi)
    except Exception as e:
        return {"task_id": task["id"], "work_id": task["work_id"], "doi": doi,
                "ok": False, "detail": f"PDF doğrulaması başarısız: {e}"}
    return {"task_id": task["id"], "work_id": task["work_id"], "doi": doi,
            "ok": True, "detail": f"{pages} sayfa / {chars} karakter", "size": path.stat().st_size}


def verify_downloads(st: State, task_ids: list[int] | None = None) -> list[dict]:
    """Dosya kaydı olan tüm görevleri (ya da verilen task_ids'i) doğrular."""
    tasks = st.list_tasks(limit=1000)
    if task_ids:
        tasks = [t for t in tasks if t["id"] in task_ids]
    results = []
    for t in tasks:
        if not st.get_files(t["work_id"]):
            continue
        results.append(verify_task(st, t))
    return results
