"""Aşama hattı: fetch-metadata / oa; görev durum makinesini ilerletir."""

from __future__ import annotations

import asyncio
import logging

import httpx

from litlib.config import paths
from litlib.download import download_to_file
from litlib.logging_setup import sanitize
from litlib.metadata import fetch_metadata
from litlib.models import TaskState, sha256_of_file
from litlib.oa import find_oa_candidates
from litlib.pdf import PDFError, validate_pdf_for_work
from litlib.state import State

logger = logging.getLogger("litlib.pipeline")

METADATA_CONCURRENCY = 4
OA_CONCURRENCY = 2
MAX_PDF_BYTES = 200 * 1024 * 1024


async def run_metadata(st: State, limit: int = 100) -> dict:
    tasks = st.list_tasks(state=TaskState.QUEUED, limit=limit)
    if not tasks:
        return {"processed": 0, "failed": 0}
    sem = asyncio.Semaphore(METADATA_CONCURRENCY)
    async with httpx.AsyncClient(timeout=30.0) as client:
        async def one(task: dict) -> bool:
            async with sem:
                st.set_state(task["id"], TaskState.METADATA_FETCH)
                work = st.get_work(task["work_id"])
                try:
                    resolved = await fetch_metadata(client, work)
                except Exception as e:
                    st.set_state(task["id"], TaskState.FAILED, error=f"metadata: {e}")
                    logger.warning("metadata failed task=%s %s", task["id"], e)
                    return False
                if not resolved.title:
                    st.set_state(task["id"], TaskState.FAILED, error="metadata çözümlenemedi")
                    return False
                try:
                    st.update_work(resolved)
                except Exception as e:
                    st.set_state(task["id"], TaskState.FAILED, error=f"metadata dedupe: {e}")
                    logger.warning("metadata dedupe failed task=%s %s", task["id"], e)
                    return False
                st.set_state(task["id"], TaskState.DEDUPED)
                return True

        results = await asyncio.gather(*(one(t) for t in tasks))
    ok = sum(1 for r in results if r)
    return {"processed": len(tasks), "ok": ok, "failed": len(tasks) - ok}


async def run_oa(st: State, limit: int = 100) -> dict:
    tasks = st.list_tasks(state=TaskState.DEDUPED, limit=limit)
    if not tasks:
        return {"processed": 0, "ok": 0, "requires_inst": 0, "failed": 0}
    sem = asyncio.Semaphore(OA_CONCURRENCY)
    stats = {"processed": 0, "ok": 0, "requires_inst": 0, "failed": 0}
    async with httpx.AsyncClient(timeout=60.0) as client:
        async def one(task: dict) -> None:
            async with sem:
                stats["processed"] += 1
                work = st.get_work(task["work_id"])
                dest = paths.staging_downloads / f"{work.work_id}.pdf"
                if dest.exists():
                    try:
                        n_pages, n_chars = validate_pdf_for_work(dest, work.doi)
                        sha = sha256_of_file(dest)
                        owner = st.dedupe_owner("sha256", sha)
                        if owner and owner != work.work_id:
                            raise ValueError(f"existing PDF belongs to work {owner}")
                        for state in (
                            TaskState.OA_OK, TaskState.DOWNLOADING,
                            TaskState.VERIFYING,
                        ):
                            st.set_state(task["id"], state)
                        st.add_file(
                            work.work_id, str(dest), sha, dest.stat().st_size,
                            "recovered-existing",
                        )
                        st.set_state(task["id"], TaskState.READY)
                        stats["ok"] += 1
                        logger.info(
                            "recovered existing PDF task=%s pages=%s chars=%s",
                            task["id"], n_pages, n_chars,
                        )
                    except Exception as e:
                        st.set_state(
                            task["id"], TaskState.FAILED,
                            error=f"existing output requires review: {e}",
                        )
                        stats["failed"] += 1
                    return
                try:
                    candidates = await find_oa_candidates(client, work)
                except Exception as e:
                    st.set_state(task["id"], TaskState.FAILED, error=f"OA discovery: {e}")
                    logger.warning("OA discovery failed task=%s %s", task["id"], e)
                    stats["failed"] += 1
                    return
                if not candidates:
                    st.set_state(task["id"], TaskState.REQUIRES_INST,
                                 error="hiçbir OA kanalı sonuç vermedi")
                    stats["requires_inst"] += 1
                    return
                errors: list[str] = []
                for oa in candidates:
                    route_id = st.start_route_attempt(task["id"], f"oa:{oa.channel}", oa.url)
                    try:
                        _, sha, size = await download_to_file(
                            client, oa.url, dest, max_bytes=MAX_PDF_BYTES)
                        n_pages, n_chars = validate_pdf_for_work(dest, work.doi)
                        owner = st.dedupe_owner("sha256", sha)
                        if owner and owner != work.work_id:
                            raise ValueError(f"PDF SHA-256 already belongs to work {owner}")
                    except (httpx.HTTPError, PDFError, ValueError, OSError) as e:
                        st.finish_route_attempt(route_id, "FAILED", str(e))
                        errors.append(f"{oa.channel}: {e}")
                        dest.unlink(missing_ok=True)
                        continue
                    try:
                        st.set_state(task["id"], TaskState.OA_OK)
                        st.set_state(task["id"], TaskState.DOWNLOADING)
                        st.set_state(task["id"], TaskState.VERIFYING)
                        work.extra["oa"] = {
                            "url": sanitize(oa.url), "channel": oa.channel,
                            "pages": n_pages, "text_chars": n_chars,
                        }
                        st.update_work(work)
                        st.add_file(work.work_id, str(dest), sha, size, oa.channel)
                        st.set_state(task["id"], TaskState.READY)
                        st.finish_route_attempt(route_id, "SUCCEEDED", size_bytes=size)
                        stats["ok"] += 1
                    except Exception as e:
                        st.finish_route_attempt(route_id, "FAILED", f"registration: {e}")
                        current = TaskState(st.get_task(task["id"])["state"])
                        if current is not TaskState.FAILED:
                            st.set_state(task["id"], TaskState.FAILED, error=f"OA registration: {e}")
                        stats["failed"] += 1
                    return
                st.set_state(task["id"], TaskState.REQUIRES_INST,
                             error="tüm OA adayları başarısız: " + " | ".join(errors)[:800])
                stats["requires_inst"] += 1

        await asyncio.gather(*(one(t) for t in tasks))
    return stats
