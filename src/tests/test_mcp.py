"""Testler: salt-okur MCP araçlarının hata yönetimi ve state yedek yolu (çalışan Zotero gerektirmez)."""

from __future__ import annotations

import json

from litlib import mcp_server


class _ZoteroDown:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("zotero unavailable")


def _state_with(tmp_path):
    from litlib.state import State
    st = State(tmp_path / "t.db")
    st.queue_add(["A test paper about epitope example"], source="test")
    return st


class TestMCP:
    def test_search_metadata_skips_attachment_items(self, monkeypatch, tmp_path):
        class FakeZot:
            def __init__(self):
                pass

            def search_items(self, query, limit=5):
                return [
                    {"key": "ATT1", "data": {"itemType": "attachment", "title": "paper.pdf"}},
                    {"key": "ART1", "data": {
                        "itemType": "journalArticle", "title": "Real Paper", "DOI": "10.1000/x",
                        "date": "2024",
                        "creators": [{"lastName": "Zhang", "firstName": "San"}]}},
                ]

            def close(self):
                pass

        monkeypatch.setattr(mcp_server, "ZoteroReadOnly", FakeZot)
        st = _state_with(tmp_path)
        monkeypatch.setattr(mcp_server, "State", lambda **kwargs: st)
        out = json.loads(mcp_server.library_search_metadata("paper", limit=5))
        keys = [x.get("key") for x in out]
        assert "ATT1" not in keys
        assert "ART1" in keys

    def test_search_metadata_state_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mcp_server, "ZoteroReadOnly", _ZoteroDown)
        st = _state_with(tmp_path)
        monkeypatch.setattr(mcp_server, "State", lambda **kwargs: st)
        out = json.loads(mcp_server.library_search_metadata("example", limit=5))
        assert isinstance(out, list)
        assert any(x.get("source") == "state" for x in out)

    def test_list_collections_error_safe(self, monkeypatch):
        monkeypatch.setattr(mcp_server, "ZoteroReadOnly", _ZoteroDown)
        out = json.loads(mcp_server.library_list_collections())
        assert isinstance(out, list)
        assert "error" in out[0]

    def test_task_status(self, monkeypatch, tmp_path):
        st = _state_with(tmp_path)
        monkeypatch.setattr(mcp_server, "State", lambda **kwargs: st)
        out = json.loads(mcp_server.library_task_status())
        assert any(x.get("state") == "QUEUED" for x in out)

    def test_get_fulltext_no_match_returns_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mcp_server, "ZoteroReadOnly", _ZoteroDown)
        st = _state_with(tmp_path)
        monkeypatch.setattr(mcp_server, "State", lambda **kwargs: st)
        out = json.loads(mcp_server.library_get_fulltext("no-such-keyword-xyz"))
        assert "error" in out

    def test_get_pdf_path_no_match_returns_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mcp_server, "ZoteroReadOnly", _ZoteroDown)
        st = _state_with(tmp_path)
        monkeypatch.setattr(mcp_server, "State", lambda **kwargs: st)
        out = json.loads(mcp_server.library_get_pdf_path("no-such-keyword-xyz"))
        assert "error" in out

    def test_get_pdf_path_falls_back_when_zotero_is_down(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mcp_server, "ZoteroReadOnly", _ZoteroDown)
        st = _state_with(tmp_path)
        work = st.search_works("example", 1)[0]
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF")
        st.add_file(work["work_id"], str(pdf), "a" * 64, pdf.stat().st_size, "test")
        monkeypatch.setattr(mcp_server, "State", lambda **kwargs: st)

        out = json.loads(mcp_server.library_get_pdf_path("example"))

        assert out["source"] == "state"
        assert out["path"] == str(pdf)

    def test_get_fulltext_disables_filesystem_cache(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            mcp_server,
            "_find_pdf",
            lambda query: {"key": "KEY", "path": str(tmp_path / "paper.pdf")},
        )

        def fake_fulltext(path, key, offset, limit_chars, *, cache):
            assert cache is False
            return {"total_chars": 4, "offset": 0, "limit_chars": 10, "text": "text"}

        monkeypatch.setattr(mcp_server, "get_fulltext", fake_fulltext)
        out = json.loads(mcp_server.library_get_fulltext("10.1000/example"))
        assert out["text"] == "text"
