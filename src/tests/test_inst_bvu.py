"""BVU (GlobalProtect VPN) kurum kolu: ön kontrol, rota seçimi, hız ayarı."""

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


# ---- ön kontrol -----------------------------------------------------------

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
])
async def test_preflight_uses_publisher_attribution(monkeypatch, status, fixture, expected):
    monkeypatch.setenv("LITLIB_BVU_PROBE_URL", PROBE_URL)
    async with _client(status, _fixture(fixture)) as client:
        ok, _ = await bvu.vpn_preflight(client)
    assert ok is expected


# ---- httpx anti-bot duvarına takılınca CDP tarayıcısına geri düşme -------------------

class FakeTab:
    """chrome_cdp.Tab yerine geçer; bir fixture'ı işlenmiş sayfa olarak sunar."""

    def __init__(self, html: str):
        self.html = html
        self.closed = self.closed_target = False

    async def connect(self):
        return None

    async def cmd(self, method, params=None):
        expression = (params or {}).get("expression", "")
        if "outerHTML" in expression:
            return {"result": {"value": self.html}}
        text = bvu.re.sub(r"<[^>]+>", " ", self.html)  # wait_for_human_challenge'ın okuduğu metin
        return {"result": {"value": text}}

    async def close(self):
        self.closed = True

    async def close_target(self):
        self.closed_target = True


@pytest.fixture()
def fake_cdp(monkeypatch):
    opened: list[str] = []
    tab = FakeTab(_fixture("sciencedirect_access.html"))

    async def wait_for_cdp(timeout=0):
        return "ws://browser"

    async def create_tab_navigate(url, timeout=0):
        opened.append(url)
        return "ws://page"

    async def no_sleep(_seconds):
        return None

    monkeypatch.setenv("LITLIB_BVU_PROBE_URL", PROBE_URL)
    monkeypatch.setattr(bvu.chrome_cdp, "wait_for_cdp", wait_for_cdp)
    monkeypatch.setattr(bvu.chrome_cdp, "create_tab_navigate", create_tab_navigate)
    monkeypatch.setattr(bvu.chrome_cdp, "Tab", lambda _ws: tab)
    monkeypatch.setattr(bvu.asyncio, "sleep", no_sleep)
    return SimpleNamespace(opened=opened, tab=tab)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 503, 200])
async def test_cloudflare_challenge_falls_back_to_cdp_browser(fake_cdp, status):
    async with _client(status, _fixture("cloudflare_challenge.html")) as client:
        ok, evidence = await bvu.vpn_preflight(client)
    assert ok, evidence
    assert "Bezmialem" in evidence and evidence.endswith("(via browser)")
    assert fake_cdp.opened == [PROBE_URL]
    assert fake_cdp.tab.closed_target and not fake_cdp.tab.closed


@pytest.mark.asyncio
async def test_browser_fallback_without_access_attribution_fails(fake_cdp):
    fake_cdp.tab.html = _fixture("sciencedirect_no_access.html")
    async with _client(403, _fixture("cloudflare_challenge.html")) as client:
        ok, reason = await bvu.vpn_preflight(client)
    assert not ok and "no BVU access attribution" in reason


@pytest.mark.asyncio
async def test_unsolved_challenge_waits_for_human_and_keeps_tab(monkeypatch, fake_cdp):
    waited: list[bool] = []

    async def human_did_not_finish(_tab):
        waited.append(True)
        return False

    monkeypatch.setattr("litlib.inst_login.wait_for_human_challenge", human_did_not_finish)
    async with _client(403, _fixture("cloudflare_challenge.html")) as client:
        ok, reason = await bvu.vpn_preflight(client)
    assert not ok and reason.startswith("HUMAN_REQUIRED")
    assert waited == [True]
    assert fake_cdp.tab.closed and not fake_cdp.tab.closed_target


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "fixture"), [
    (200, "sciencedirect_no_access.html"),   # gerçek "erişim yok" Chrome'da yeniden denenmez
    (429, "cloudflare_challenge.html"),      # hız sınırı durdurur, asla bir üst adıma geçmez
])
async def test_no_browser_escalation(fake_cdp, status, fixture):
    async with _client(status, _fixture(fixture)) as client:
        ok, reason = await bvu.vpn_preflight(client)
    assert not ok
    assert fake_cdp.opened == []
    if status == 429:
        assert reason.startswith("RATE_LIMITED")


@pytest.mark.asyncio
async def test_browser_fallback_reports_missing_dedicated_chrome(monkeypatch):
    async def cdp_down(timeout=0):
        raise TimeoutError

    monkeypatch.setenv("LITLIB_BVU_PROBE_URL", PROBE_URL)
    monkeypatch.setattr(bvu.chrome_cdp, "wait_for_cdp", cdp_down)
    async with _client(403, _fixture("cloudflare_challenge.html")) as client:
        ok, reason = await bvu.vpn_preflight(client)
    assert not ok and "litlib inst open" in reason


# ---- BVU altında run_inst davranışı-----------------------------------------

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
        dest.write_bytes(b"%PDF-1.7 " + doi.encode())  # farklı baytlar: SHA-256 tekilleştirmesi gerçekten çalışır
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
    ("HUMAN_REQUIRED: insan doğrulaması kullanıcı tarafından henüz tamamlanmadı", TaskState.HUMAN_REQUIRED),
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
