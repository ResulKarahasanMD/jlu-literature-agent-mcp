from __future__ import annotations

import hashlib
from types import SimpleNamespace

import httpx
import pytest
from reportlab.pdfgen import canvas

from litlib.models import TaskState
from litlib.oa import OAResult
from litlib.pipeline import run_oa
from litlib.state import State


def _article_pdf(path, doi="10.1000/right"):
    document = canvas.Canvas(str(path))
    document.drawString(72, 760, f"Research Article DOI: {doi}")
    document.save()
    with path.open("ab") as handle:
        handle.write(b" " * 5_000)
    return path


@pytest.mark.asyncio
async def test_oa_download_tries_next_candidate(monkeypatch, tmp_path):
    state = State(tmp_path / "state.db")
    state.queue_add(["10.1000/right"])
    task = state.list_tasks()[0]
    state.set_state(task["id"], TaskState.METADATA_FETCH)
    work = state.get_work(task["work_id"])
    work.title = "Right article"
    state.update_work(work)
    state.set_state(task["id"], TaskState.DEDUPED)

    async def candidates(client, work):
        return [
            OAResult(True, "https://bad.example/a.pdf", "bad"),
            OAResult(True, "https://good.example/a.pdf", "good"),
        ]

    calls = []

    async def downloader(client, url, dest, max_bytes=None):
        calls.append(url)
        if "bad.example" in url:
            request = httpx.Request("GET", url)
            response = httpx.Response(403, request=request)
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)
        _article_pdf(dest)
        data = dest.read_bytes()
        return dest, hashlib.sha256(data).hexdigest(), len(data)

    import litlib.pipeline as pipeline
    monkeypatch.setattr(pipeline, "find_oa_candidates", candidates)
    monkeypatch.setattr(pipeline, "download_to_file", downloader)
    monkeypatch.setattr(pipeline, "paths", SimpleNamespace(staging_downloads=tmp_path))

    result = await run_oa(state)
    assert result["ok"] == 1
    assert calls == ["https://bad.example/a.pdf", "https://good.example/a.pdf"]
    assert state.get_task(task["id"])["state"] == TaskState.READY.value
    assert state.get_files(work.work_id)[0]["channel"] == "good"
    attempts = state.get_route_attempts(task["id"])
    assert [(row["route"], row["outcome"]) for row in attempts] == [
        ("oa:bad", "FAILED"), ("oa:good", "SUCCEEDED"),
    ]
    state.close()


@pytest.mark.asyncio
async def test_oa_recovers_valid_existing_pdf_without_overwrite(monkeypatch, tmp_path):
    state = State(tmp_path / "state.db")
    state.queue_add(["10.1000/right"])
    task = state.list_tasks()[0]
    state.set_state(task["id"], TaskState.METADATA_FETCH)
    work = state.get_work(task["work_id"])
    work.title = "Recovered article"
    state.update_work(work)
    state.set_state(task["id"], TaskState.DEDUPED)
    existing = _article_pdf(tmp_path / f"{work.work_id}.pdf")
    before = existing.read_bytes()

    import litlib.pipeline as pipeline
    monkeypatch.setattr(pipeline, "paths", SimpleNamespace(staging_downloads=tmp_path))

    result = await run_oa(state)

    assert result["ok"] == 1
    assert existing.read_bytes() == before
    assert state.get_files(work.work_id)[0]["channel"] == "recovered-existing"
    state.close()


@pytest.mark.asyncio
async def test_oa_preserves_invalid_existing_pdf_for_review(monkeypatch, tmp_path):
    state = State(tmp_path / "state.db")
    state.queue_add(["10.1000/right"])
    task = state.list_tasks()[0]
    state.set_state(task["id"], TaskState.METADATA_FETCH)
    work = state.get_work(task["work_id"])
    work.title = "Invalid recovery article"
    state.update_work(work)
    state.set_state(task["id"], TaskState.DEDUPED)
    existing = tmp_path / f"{work.work_id}.pdf"
    existing.write_bytes(b"not a PDF")

    import litlib.pipeline as pipeline
    monkeypatch.setattr(pipeline, "paths", SimpleNamespace(staging_downloads=tmp_path))

    result = await run_oa(state)

    assert result["failed"] == 1
    assert existing.read_bytes() == b"not a PDF"
    assert state.get_task(task["id"])["state"] == TaskState.FAILED.value
    state.close()
