"""BVU (GlobalProtect VPN) institution branch: preflight, route selection, pacing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from litlib import bvu, inst
from litlib.inst import BATCH_LIMIT, DELAY, run_inst
from litlib.models import TaskState
from litlib.pdf import PDFError
from litlib.state import State

FIXTURES = Path(__file__).parent / "fixtures" / "bvu"
PROBE_URL = "https://www.sciencedirect.test/science/article/pii/EXAMPLE"
ELSEVIER_DOIS = ["10.1016/j.example.2024.000001", "10.1016/j.example.2024.000002"]


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client(status: int, body: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, text=body)))


async def _raise(*_args, **_kwargs):
    raise AssertionError("JLU route must not run for BVU")


@pytest.fixture()
def bvu_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LITLIB_INSTITUTION", "bvu")
    monkeypatch.setenv("LITLIB_BVU_PROBE_URL", PROBE_URL)
    monkeypatch.setattr(inst, "paths", SimpleNamespace(staging_downloads=tmp_path))
    monkeypatch.setattr(inst, "_record_inst_experience", lambda *a, **k: None)
    monkeypatch.setattr(inst, "get_vpn_cookies", _raise)
    monkeypatch.setattr("litlib.inst_login.login_and_download_doi", _raise)
    monkeypatch.setattr("litlib.inst_login.resolve_doi_host", _raise)
    sleeps: list[float] = []
    monkeypatch.setattr(inst.time, "sleep", sleeps.append)
    return sleeps


@pytest.fixture()
def state(tmp_path):
    s = State(tmp_path / "test.db")
    s.queue_add(ELSEVIER_DOIS)
    for task in s.list_tasks():
        for step in (TaskState.METADATA_FETCH, TaskState.DEDUPED, TaskState.REQUIRES_INST):
            s.set_state(task["id"], step)
    yield s
    s.close()


def _preflight(monkeypatch, ok: bool, evidence: str = "Access provided by Bezmialem"):
    async def fake(_client):
        return ok, evidence
    monkeypatch.setattr(inst.bvu, "vpn_preflight", fake)


# ---- preflight -------------------------------------------------------------

def test_is_active_reads_env(monkeypatch):
    monkeypatch.delenv("LITLIB_INSTITUTION", raising=False)
    assert not bvu.is_active()
    monkeypatch.setenv("LITLIB_INSTITUTION", "BVU")
    assert bvu.is_active()


def test_access_attribution_detected_in_fixture():
    evidence = bvu.detect_institutional_access(_fixture("sciencedirect_access.html"))
    assert "Bezmialem Vakif University" in evidence
    assert "<" not in evidence
    assert bvu.detect_institutional_access(_fixture("sciencedirect_no_access.html")) == ""


@pytest.mark.asyncio
async def test_preflight_requires_probe_url(monkeypatch):
    monkeypatch.delenv("LITLIB_BVU_PROBE_URL", raising=False)
    async with _client(200, _fixture("sciencedirect_access.html")) as client:
        ok, reason = await bvu.vpn_preflight(client)
    assert not ok and "LITLIB_BVU_PROBE_URL" in reason


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "fixture", "expected"), [
    (200, "sciencedirect_access.html", True),
    (200, "sciencedirect_no_access.html", False),
    (403, "sciencedirect_access.html", False),
])
async def test_preflight_uses_publisher_attribution(monkeypatch, status, fixture, expected):
    monkeypatch.setenv("LITLIB_BVU_PROBE_URL", PROBE_URL)
    async with _client(status, _fixture(fixture)) as client:
        ok, _ = await bvu.vpn_preflight(client)
    assert ok is expected


# ---- run_inst behaviour under BVU -------------------------------------------

def test_rate_limits_unchanged():
    assert BATCH_LIMIT == 10
    assert DELAY == (8, 15)


@pytest.mark.asyncio
async def test_failed_preflight_pauses_without_touching_tasks(monkeypatch, bvu_env, state):
    _preflight(monkeypatch, False, "probe page has no BVU access attribution")
    monkeypatch.setattr("litlib.inst_login.download_doi_via_browser", _raise)
    stats = await run_inst(state)
    assert stats["paused"] == 2 and stats["processed"] == 0
    assert all(t["state"] == TaskState.REQUIRES_INST.value for t in state.list_tasks())
    assert bvu_env == []


@pytest.mark.asyncio
async def test_success_uses_only_direct_routes_and_paces(monkeypatch, bvu_env, state, tmp_path):
    _preflight(monkeypatch, True)

    async def fake_browser(doi, dest):
        dest.write_bytes(b"%PDF-1.7 " + doi.encode())  # distinct bytes: SHA-256 dedupe is real
        return {"size": dest.stat().st_size, "content_type": "application/pdf"}

    monkeypatch.setattr("litlib.inst_login.download_doi_via_browser", fake_browser)
    monkeypatch.setattr(inst, "validate_pdf_for_work", lambda _dest, _doi: (3, 5000))
    stats = await run_inst(state, access_mode="offcampus")

    assert stats["ok"] == 2
    for task in state.list_tasks():
        assert task["state"] == TaskState.READY.value
        routes = [a["route"] for a in state.get_route_attempts(task["id"])]
        assert routes == ["direct-browser"]
    assert len(bvu_env) == 2
    assert all(DELAY[0] <= d <= DELAY[1] for d in bvu_env)


@pytest.mark.asyncio
@pytest.mark.parametrize(("error", "expected"), [
    ("HUMAN_REQUIRED: 人机验证尚未由用户完成", TaskState.HUMAN_REQUIRED),
    ("HTTP 429 too many requests", TaskState.RATE_LIMITED),
])
async def test_checkpoint_stops_batch(monkeypatch, bvu_env, state, error, expected):
    _preflight(monkeypatch, True)
    calls: list[str] = []

    async def challenged(doi, _dest):
        calls.append(doi)
        raise PDFError(error)

    monkeypatch.setattr("litlib.inst_login.download_doi_via_browser", challenged)
    stats = await run_inst(state, access_mode="auto")

    assert calls == [ELSEVIER_DOIS[0]]
    assert stats["processed"] == 1 and stats["paused"] == 1
    by_doi = {state.get_work(t["work_id"]).doi: t["state"] for t in state.list_tasks()}
    assert by_doi[ELSEVIER_DOIS[0]] == expected.value
    assert by_doi[ELSEVIER_DOIS[1]] == TaskState.REQUIRES_INST.value
    assert bvu_env == []
