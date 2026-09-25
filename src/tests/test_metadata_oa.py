"""Testler: metadata normalleştirme, OA kanalları, akışlı indirme."""

from __future__ import annotations

import httpx
import pytest

from litlib.download import download_to_file
from litlib.metadata import (
    _author_parts,
    _crossref_to_work,
    _datacite_to_work,
    _pubmed_to_work,
    fetch_metadata,
    merge_work,
    resolve_by_arxiv,
    resolve_by_doi,
)
from litlib.models import Work, arxiv_id_from_doi
from litlib.oa import (
    arxiv_direct,
    crossref_link,
    find_oa,
    find_oa_candidates,
    mdpi_static_pdf,
    unpaywall,
)

CROSSREF_MSG = {
    "DOI": "10.1000/XYZ.2024.123",
    "title": ["A Landmark Study of Everything"],
    "container-title": ["Journal of Everything"],
    "issued": {"date-parts": [[2024, 5, 1]]},
    "volume": "42",
    "issue": "3",
    "page": "100-110",
    "publisher": "Example Publisher",
    "author": [
        {"family": "Zhang", "given": "San", "ORCID": "http://orcid.org/0000-0001-2345-6789"},
        {"family": "Li", "given": "Si"},
    ],
    "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
    "link": [
        {"URL": "https://example.com/pdf/a.pdf", "content-type": "application/pdf",
         "intended-application": "text-mining"},
        {"URL": "https://example.com/fulltext", "content-type": "text/html",
         "intended-application": "text-mining"},
    ],
    "type": "journal-article",
}

PUBMED_DOC = {
    "uid": "12345678",
    "title": "A PubMed Study.",
    "pubdate": "2023 Jul 15",
    "fulljournalname": "Journal of PubMed",
    "volume": "10",
    "issue": "2",
    "pages": "55-60",
    "authors": [{"name": "Wang Wu"}],
    "articleids": [
        {"idtype": "doi", "value": "10.2000/ABC.2023.1"},
        {"idtype": "pmc", "value": "PMC9999999"},
    ],
}

DATACITE_DATA = {
    "attributes": {
        "doi": "10.13021/MARS/15267",
        "titles": [{"title": "A Repository Thesis"}],
        "publicationYear": 2024,
        "publisher": "George Mason University",
        "creators": [{"familyName": "Tsen", "givenName": "Daniel"}],
        "types": {"resourceTypeGeneral": "Text"},
        "url": "https://example.edu/record/1",
    }
}


class TestMetadataNormalization:
    def test_author_name_forms(self):
        assert _author_parts("Smith J") == ("Smith", "J")
        assert _author_parts("Jane Doe") == ("Doe", "Jane")
        assert _author_parts("Doe, Jane") == ("Doe", "Jane")

    def test_crossref(self):
        w = _crossref_to_work(CROSSREF_MSG)
        assert w.doi == "10.1000/xyz.2024.123"
        assert w.title == "A Landmark Study of Everything"
        assert w.year == 2024
        assert w.journal == "Journal of Everything"
        assert w.volume == "42" and w.pages == "100-110"
        assert w.authors[0]["family"] == "Zhang"
        assert w.authors[0]["orcid"] == "0000-0001-2345-6789"
        assert w.extra["crossref"]["license"] == ["https://creativecommons.org/licenses/by/4.0/"]

    def test_pubmed(self):
        w = _pubmed_to_work(PUBMED_DOC)
        assert w.pmid == "12345678"
        assert w.title == "A PubMed Study"
        assert w.year == 2023
        assert w.doi == "10.2000/abc.2023.1"
        assert w.pmcid == "PMC9999999"

    def test_datacite(self):
        w = _datacite_to_work(DATACITE_DATA)
        assert w.doi == "10.13021/mars/15267"
        assert w.title == "A Repository Thesis"
        assert w.extra["datacite"]["type"] == "Text"

    def test_merge_prefers_existing(self):
        base = Work(doi="10.1000/xyz", title="Base Title")
        incoming = Work(doi="10.other/xyz", title="Incoming Title", pmid="1")
        merged = merge_work(base, incoming)
        assert merged.doi == "10.1000/xyz"
        assert merged.title == "Base Title"
        assert merged.pmid == "1"


class TestResolveByDOI:
    @pytest.mark.asyncio
    async def test_ok(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"message": CROSSREF_MSG})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            w = await resolve_by_doi(client, "10.1000/XYZ.2024.123")
        assert w.title == "A Landmark Study of Everything"
        assert w.year == 2024

    @pytest.mark.asyncio
    async def test_datacite_fallback(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "crossref" in str(request.url):
                return httpx.Response(404)
            return httpx.Response(200, json={"data": DATACITE_DATA})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            w = await resolve_by_doi(client, "10.13021/MARS/15267")
        assert w.title == "A Repository Thesis"

    @pytest.mark.asyncio
    async def test_datacite_fallback_after_crossref_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "crossref" in str(request.url):
                return httpx.Response(500)
            return httpx.Response(200, json={"data": DATACITE_DATA})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            w = await resolve_by_doi(client, "10.13021/MARS/15267")
        assert w.title == "A Repository Thesis"

    @pytest.mark.asyncio
    async def test_arxiv(self):
        atom = """<?xml version='1.0'?>
        <feed xmlns='http://www.w3.org/2005/Atom' xmlns:arxiv='http://arxiv.org/schemas/atom'>
          <entry><title> A useful preprint </title><published>2024-01-01T00:00:00Z</published>
          <author><name>Jane Doe</name></author><arxiv:doi>10.1000/XYZ</arxiv:doi></entry>
        </feed>"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=atom)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            w = await resolve_by_arxiv(client, "2401.00001")
        assert w.title == "A useful preprint"
        assert w.doi == "10.1000/xyz"


class TestArxivDOI:
    """arXiv'in DataCite DOI'si (10.48550/arXiv.<id>) arXiv ID'sine eşlenmelidir."""

    def test_arxiv_id_from_doi(self):
        assert arxiv_id_from_doi("10.48550/arXiv.1706.03762") == "1706.03762"
        assert arxiv_id_from_doi("https://doi.org/10.48550/ARXIV.2401.00001") == "2401.00001"
        assert arxiv_id_from_doi("10.48550/arXiv.hep-th/9901001") == "hep-th/9901001"
        assert arxiv_id_from_doi("10.1038/s41586-025-08610-1") is None
        assert arxiv_id_from_doi(None) is None

    @pytest.mark.asyncio
    async def test_arxiv_direct_derives_id_from_doi(self):
        result = await arxiv_direct(None, Work(doi="10.48550/arxiv.1706.03762"))
        assert result.found
        assert result.url == "https://arxiv.org/pdf/1706.03762"

    @pytest.mark.asyncio
    async def test_fetch_metadata_sets_arxiv_from_datacite_doi(self):
        datacite = {"attributes": {
            "doi": "10.48550/ARXIV.1706.03762",
            "titles": [{"title": "Attention Is All You Need"}],
            "publicationYear": 2017,
            "creators": [{"familyName": "Vaswani", "givenName": "Ashish"}],
            "types": {"resourceTypeGeneral": "Preprint"},
        }}

        def handler(request: httpx.Request) -> httpx.Response:
            if "datacite" in str(request.url):
                return httpx.Response(200, json={"data": datacite})
            return httpx.Response(404)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            w = await fetch_metadata(client, Work(doi="10.48550/arxiv.1706.03762"))
        assert w.title == "Attention Is All You Need"
        assert w.arxiv == "1706.03762"


class TestOAFind:
    @pytest.mark.asyncio
    async def test_mdpi_static_pdf_url(self):
        result = await mdpi_static_pdf(None, Work(doi="10.3390/antib12030052"))
        assert result.found
        assert result.url.endswith("/antibodies-12-00052/article_deploy/antibodies-12-00052.pdf")

    @pytest.mark.asyncio
    async def test_unpaywall_found(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "unpaywall.org" in str(request.url)
            return httpx.Response(200, json={
                "is_oa": True,
                "best_oa_location": {"url_for_pdf": "https://oa.example.com/a.pdf"},
            })

        monkeypatch.setenv("LITLIB_EMAIL", "me@example.com")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await unpaywall(client, Work(doi="10.1000/xyz"))
        assert result.found and result.url == "https://oa.example.com/a.pdf"
        assert result.channel == "unpaywall"

    @pytest.mark.asyncio
    async def test_unpaywall_requires_email(self, monkeypatch):
        monkeypatch.delenv("LITLIB_EMAIL", raising=False)
        async with httpx.AsyncClient() as client:
            result = await unpaywall(client, Work(doi="10.1000/xyz"))
        assert not result.found

    @pytest.mark.asyncio
    async def test_crossref_tdm_only_is_not_oa(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"message": CROSSREF_MSG})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await crossref_link(client, Work(doi="10.1000/xyz.2024.123"))
        assert not result.found

    @pytest.mark.asyncio
    async def test_crossref_open_non_tdm_link(self):
        msg = dict(CROSSREF_MSG)
        msg["link"] = [{
            "URL": "https://example.com/article.pdf",
            "content-type": "application/pdf",
            "intended-application": "syndication",
        }]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"message": msg})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await crossref_link(client, Work(doi="10.1000/xyz.2024.123"))
        assert result.found and result.channel == "crossref_link"

    @pytest.mark.asyncio
    async def test_find_oa_falls_through(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"is_oa": False, "best_oa_location": None})

        monkeypatch.setenv("LITLIB_EMAIL", "me@example.com")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await find_oa(client, Work(doi="10.1000/xyz", pmcid="PMC1"))
        assert not result.found

    @pytest.mark.asyncio
    async def test_candidate_provider_error_does_not_block_fallback(self, monkeypatch):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if "unpaywall.org" in str(request.url):
                return httpx.Response(500)
            if "europepmc" in str(request.url):
                return httpx.Response(200, json={
                    "resultList": {"result": [{"isOpenAccess": "Y", "pmcid": "PMC1"}]},
                })
            return httpx.Response(404)

        monkeypatch.setenv("LITLIB_EMAIL", "me@example.com")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            results = await find_oa_candidates(client, Work(doi="10.1000/xyz", pmcid="PMC1"))
        assert results[0].channel == "europe_pmc"
        assert any("unpaywall.org" in url for url in calls)
        assert any("europepmc" in url for url in calls)


class TestDownload:
    @pytest.mark.asyncio
    async def test_streaming_and_hash(self, tmp_path):
        payload = b"%PDF-1.4 fake content " * 1000
        expected_hash = __import__("hashlib").sha256(payload).hexdigest()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=payload)

        dest = tmp_path / "out.pdf"
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            final, sha, size = await download_to_file(client, "https://x/a.pdf", dest)
        assert final == dest and sha == expected_hash and size == len(payload)
        assert not (tmp_path / "out.pdf.part").exists()

    @pytest.mark.asyncio
    async def test_max_bytes_aborts(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 1024 * 1024)

        dest = tmp_path / "big.pdf"
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError):
                await download_to_file(client, "https://x/big.pdf", dest, max_bytes=100)
        assert not dest.exists()
