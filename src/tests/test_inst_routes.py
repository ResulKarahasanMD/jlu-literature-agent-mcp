from __future__ import annotations

import httpx
import pytest

from litlib.inst import (
    BATCH_LIMIT,
    GATEWAY,
    doi_to_publisher,
    download_via_gateway,
    extract_gateway_token,
    gateway_url,
    run_inst,
)
from litlib.inst_login import (
    auto_login,
    download_doi_via_browser,
    fetch_pdf_via_browser,
    fill_idp_login,
    handle_post_login,
    is_allowed_jlu_idp_url,
    is_explicit_paywall,
    known_pdf_url,
    submit_idp_login,
)
from litlib.pdf import PDFError


def test_gateway_url_keeps_token_prefix():
    url = gateway_url({"nature.com": "abc123"}, "nature.com", "articles/paper.pdf")
    assert url == f"{GATEWAY}/https/abc123/articles/paper.pdf"


def test_extract_gateway_token():
    assert extract_gateway_token(
        "https://vpn.jlu.edu.cn/https/abc123/articles/paper.pdf") == "abc123"
    assert extract_gateway_token("https://nature.com/articles/paper.pdf") == ""


def test_unknown_doi_is_not_blocked_by_mapping():
    assert doi_to_publisher("10.5555/unknown") is None


def test_known_pdf_urls_prefer_main_article():
    assert known_pdf_url("10.1126/sciadv.x") == "https://www.science.org/doi/pdf/10.1126/sciadv.x"
    assert known_pdf_url("10.1038/s42256-024-1") == "https://www.nature.com/articles/s42256-024-1.pdf"


@pytest.mark.asyncio
async def test_browser_fetch_size_limit(tmp_path):
    class FakeTab:
        async def cmd(self, method, params=None):
            if "delete window" in (params or {}).get("expression", ""):
                return {}
            return {"result": {"value": "OK:6000"}}

    with pytest.raises(PDFError, match="boyut üst sınır"):
        await fetch_pdf_via_browser(
            FakeTab(), "https://example.test/a.pdf", tmp_path / "a.pdf", max_bytes=5000)


@pytest.mark.asyncio
async def test_gateway_failure_cleans_partial_file(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>login</html>", headers={"content-type": "text/html"})

    dest = tmp_path / "out.pdf"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PDFError, match="PDF değil"):
            await download_via_gateway(client, {}, "https://vpn.example.test/x", dest)
    assert not dest.exists()
    assert not dest.with_suffix(".part").exists()


def test_jlu_idp_allowlist_requires_https_and_exact_host(monkeypatch):
    monkeypatch.setenv("LITLIB_JLU_IDP_HOSTS", "new-idp.jlu.edu.cn")
    assert is_allowed_jlu_idp_url("https://login.jlu.edu.cn/login")
    assert is_allowed_jlu_idp_url("https://new-idp.jlu.edu.cn/sso")
    assert not is_allowed_jlu_idp_url("http://login.jlu.edu.cn/login")
    assert not is_allowed_jlu_idp_url("https://login.jlu.edu.cn.evil.test/login")
    assert not is_allowed_jlu_idp_url("https://publisher.example/login")


def test_explicit_paywall_detection_is_narrow():
    assert is_explicit_paywall("Buy Protocol")
    assert is_explicit_paywall("$104 / 48 hours", "text/HTML")
    assert is_explicit_paywall("购买全文")
    assert not is_explicit_paywall("Subscribe to our newsletter", "text/HTML")
    assert not is_explicit_paywall("Open access article", "application/pdf")


@pytest.mark.asyncio
async def test_fill_idp_login_refuses_untrusted_host():
    class FakeTab:
        async def cmd(self, method, params=None):
            return {"result": {"value": "https://publisher.example/login"}}

    with pytest.raises(PermissionError, match="güvenilir olmayan IdP"):
        await fill_idp_login(FakeTab(), "student", "password")


@pytest.mark.asyncio
async def test_login_submit_does_not_accept_terms():
    expressions = []

    class FakeTab:
        async def cmd(self, method, params=None):
            expressions.append((params or {}).get("expression", ""))
            return {"result": {"value": "submitted:login"}}

    assert await submit_idp_login(FakeTab()) == "submitted:login"
    expression = "\n".join(expressions)
    assert "checkbox" not in expression
    assert "radio" not in expression
    assert "accepted:" not in expression


@pytest.mark.asyncio
async def test_terms_page_becomes_human_checkpoint(monkeypatch):
    ticks = iter((0.0, 0.0, 2.0))

    class FakeTime:
        @staticmethod
        def monotonic():
            return next(ticks)

    monkeypatch.setattr("litlib.inst_login.time", FakeTime())

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("litlib.inst_login.asyncio.sleep", no_sleep)

    class FakeTab:
        async def cmd(self, method, params=None):
            expression = (params or {}).get("expression", "")
            if expression == "location.href":
                return {"result": {"value": "https://idp.jlu.edu.cn/terms"}}
            return {"result": {"value": "声明：请同意此使用条款并提交"}}

    result = await handle_post_login(FakeTab(), host_hint="example.test", timeout=1)
    assert result.startswith("human-required:terms:")


@pytest.mark.asyncio
async def test_institution_batch_is_clamped_to_ten():
    class FakeState:
        requested_limit = None

        def list_tasks(self, state=None, limit=100):
            self.requested_limit = limit
            return []

    state = FakeState()
    result = await run_inst(state, limit=100)
    assert state.requested_limit == BATCH_LIMIT
    assert result["processed"] == 0


@pytest.mark.asyncio
async def test_auto_login_keeps_initial_challenge_tab_open(monkeypatch):
    class FakeTab:
        closed = False
        target_closed = False

        def __init__(self, _ws):
            pass

        async def connect(self):
            pass

        async def close(self):
            self.closed = True

        async def close_target(self):
            self.target_closed = True

    tab = FakeTab("ws")
    monkeypatch.setattr("litlib.inst_login.chrome_cdp.create_tab_navigate", lambda *a, **k: _async("ws"))
    monkeypatch.setattr("litlib.inst_login.chrome_cdp.Tab", lambda _ws: tab)
    monkeypatch.setattr("litlib.inst_login.wait_for_human_challenge", lambda _tab: _async(False))
    monkeypatch.setattr("litlib.inst_login.asyncio.sleep", lambda _seconds: _async(None))

    result = await auto_login("https://publisher.example", host_hint="publisher.example")

    assert result["human_required"] is True
    assert tab.closed is True
    assert tab.target_closed is False


@pytest.mark.asyncio
async def test_direct_download_keeps_challenge_tab_open(monkeypatch, tmp_path):
    class FakeTab:
        closed = False
        target_closed = False

        def __init__(self, _ws):
            pass

        async def connect(self):
            pass

        async def cmd(self, method, params=None):
            return {"result": {"value": "Are you a robot? CAPTCHA"}}

        async def close(self):
            self.closed = True

        async def close_target(self):
            self.target_closed = True

    class FakeTime:
        ticks = iter((0.0, 181.0))

        @classmethod
        def monotonic(cls):
            return next(cls.ticks)

    tab = FakeTab("ws")
    monkeypatch.setattr("litlib.inst_login.chrome_cdp.create_tab_navigate", lambda *a, **k: _async("ws"))
    monkeypatch.setattr("litlib.inst_login.chrome_cdp.Tab", lambda _ws: tab)
    monkeypatch.setattr("litlib.inst_login.find_pdf_link", lambda _tab: _async(""))
    monkeypatch.setattr("litlib.inst_login.asyncio.sleep", lambda _seconds: _async(None))
    monkeypatch.setattr("litlib.inst_login.time", FakeTime)

    with pytest.raises(PDFError, match="HUMAN_REQUIRED"):
        await download_doi_via_browser("10.1000/challenge", tmp_path / "paper.pdf")

    assert tab.closed is True
    assert tab.target_closed is False


async def _async(value):
    return value
