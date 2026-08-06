"""测试：Zotero 只读 API（mock）与全文缓存。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from reportlab.pdfgen import canvas

from litlib.fulltext import get_fulltext
from litlib.models import Work
from litlib.zotero_api import ZoteroReadOnly

ATTACHMENT_ITEM = {
    "key": "AAAA1111",
    "data": {
        "itemType": "attachment",
        "contentType": "application/pdf",
        "linkMode": "imported_file",
        "path": "storage:paper.pdf",
    },
}

PARENT_ITEM = {
    "key": "BBBB2222",
    "data": {"itemType": "journalArticle", "title": "A Zotero Study"},
}


def _make_pdf(path: Path) -> Path:
    document = canvas.Canvas(str(path))
    document.drawString(72, 760, "Hello litlib fulltext. Alpha helix results.")
    document.save()
    return path


class TestZoteroReadOnly:
    def test_list_collections(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "127.0.0.1"
            return httpx.Response(200, json=[{"key": "C1", "data": {"name": "My Papers"}}])

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            zot = ZoteroReadOnly(client)
            assert zot.list_collections() == [{"key": "C1", "data": {"name": "My Papers"}}]

    def test_attachment_abs_path(self, tmp_path: Path):
        storage = tmp_path / "storage" / "AAAA1111"
        storage.mkdir(parents=True)
        (storage / "paper.pdf").write_bytes(b"%PDF-1.4")
        zot = ZoteroReadOnly(data_dir=tmp_path)
        p = zot.attachment_abs_path(ATTACHMENT_ITEM)
        assert p == storage / "paper.pdf"

    def test_attachment_file_uri_resolves_on_windows(self, tmp_path: Path):
        pdf = tmp_path / "paper with spaces.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        attachment = {
            "key": "URI00001",
            "links": {"enclosure": {"href": pdf.as_uri()}},
            "data": {"itemType": "attachment", "contentType": "application/pdf"},
        }
        zot = ZoteroReadOnly(data_dir=tmp_path)
        assert zot.attachment_abs_path(attachment) == pdf

    def test_resolve_pdf_children(self, tmp_path: Path):
        storage = tmp_path / "storage" / "AAAA1111"
        storage.mkdir(parents=True)
        (storage / "paper.pdf").write_bytes(b"%PDF-1.4")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[ATTACHMENT_ITEM])

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            zot = ZoteroReadOnly(client, data_dir=tmp_path)
            hit = zot.resolve_pdf(PARENT_ITEM)
        assert hit == {"key": "AAAA1111", "path": storage / "paper.pdf"}

    def test_resolve_pdf_no_children(self, tmp_path: Path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            zot = ZoteroReadOnly(client, data_dir=tmp_path)
            assert zot.resolve_pdf(PARENT_ITEM) is None

    def test_find_exact_items_does_not_accept_doi_substrings(self):
        items = [
            {"key": "EXACT001", "data": {"itemType": "journalArticle", "DOI": "10.1000/x"}},
            {"key": "WRONG001", "data": {"itemType": "journalArticle", "DOI": "10.1000/x-extra"}},
            {"key": "ATTACH01", "data": {"itemType": "attachment", "DOI": "10.1000/x"}},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=items)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            zot = ZoteroReadOnly(client)
            matches = zot.find_exact_items(Work(doi="https://doi.org/10.1000/X"))
        assert [item["key"] for item in matches] == ["EXACT001"]

    def test_find_exact_items_uses_unicode_safe_exact_title(self):
        items = [
            {"key": "TITLE001", "data": {"itemType": "journalArticle", "title": "猪病毒 研究"}},
            {"key": "WRONG002", "data": {"itemType": "journalArticle", "title": "猪细菌研究"}},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=items)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            zot = ZoteroReadOnly(client)
            matches = zot.find_exact_items(Work(title="猪病毒研究"))
        assert [item["key"] for item in matches] == ["TITLE001"]

    def test_find_exact_items_falls_back_to_title_when_zotero_doi_is_missing(self):
        item = {
            "key": "TITLE002",
            "data": {"itemType": "journalArticle", "title": "Exact fallback title", "DOI": ""},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            query = request.url.params.get("q")
            return httpx.Response(200, json=[] if query.startswith("10.") else [item])

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            zot = ZoteroReadOnly(client)
            matches = zot.find_exact_items(
                Work(doi="10.1000/fallback", title="Exact fallback title")
            )
        assert [result["key"] for result in matches] == ["TITLE002"]


class TestFulltext:
    @pytest.fixture(autouse=True)
    def _isolate_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from litlib import fulltext
        monkeypatch.setattr(fulltext, "_cache_root", tmp_path / "fulltext")

    def test_paging_and_cache(self, tmp_path: Path):
        pdf = _make_pdf(tmp_path / "paper.pdf")
        r1 = get_fulltext(pdf, "KEY1", offset=0, limit_chars=1000)
        assert r1["total_chars"] > 0 and r1["from_cache"] is False
        r2 = get_fulltext(pdf, "KEY1", offset=0, limit_chars=1000)
        assert r2["from_cache"] is True
        assert r2["text"] == r1["text"]
        r3 = get_fulltext(pdf, "KEY1", offset=5, limit_chars=10)
        assert r3["text"] == r1["text"][5:15]
        assert r3["total_chars"] == r1["total_chars"]

    def test_limit_capped(self, tmp_path: Path):
        pdf = _make_pdf(tmp_path / "paper.pdf")
        r = get_fulltext(pdf, "KEY2", limit_chars=999_999)
        assert r["limit_chars"] == 20_000

    def test_cache_invalidation_on_change(self, tmp_path: Path):
        pdf = _make_pdf(tmp_path / "paper.pdf")
        get_fulltext(pdf, "KEY3", limit_chars=100)
        pdf.write_bytes(pdf.read_bytes() + b"%changed")
        r = get_fulltext(pdf, "KEY3", limit_chars=100)
        assert r["from_cache"] is False
