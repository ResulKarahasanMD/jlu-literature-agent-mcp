"""元数据解析：Crossref / PubMed / OpenAlex，归一化为 Work。"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from litlib.models import Work

CROSSREF_BASE = "https://api.crossref.org/works"
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
OPENALEX_BASE = "https://api.openalex.org/works"
DATACITE_BASE = "https://api.datacite.org/dois"
ARXIV_BASE = "https://export.arxiv.org/api/query"

CONTACT_EMAIL = os.environ.get("LITLIB_EMAIL", "litlib@example.invalid")
HEADERS = {
    "User-Agent": f"litlib/0.1 (mailto:{CONTACT_EMAIL})",
    "Accept": "application/json",
}


def _author_parts(name: str) -> tuple[str | None, str | None]:
    """Split common `Family, Given`, `Given Family`, and PubMed `Family Initials` forms."""
    name = " ".join(name.split())
    if not name:
        return None, None
    if "," in name:
        family, given = (part.strip() for part in name.split(",", 1))
        return family or None, given or None
    parts = name.rsplit(" ", 1)
    if len(parts) == 1:
        return parts[0], None
    first, last = parts
    if len(last) <= 4 and last.replace("-", "").isalpha() and last.upper() == last:
        return first or None, last or None
    return last or None, first or None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
)
async def _get(client: httpx.AsyncClient, url: str) -> dict | None:
    resp = await client.get(url, headers=HEADERS, follow_redirects=True)
    if resp.status_code in (404, 422):
        return None
    resp.raise_for_status()
    return resp.json()


def _crossref_to_work(msg: dict) -> Work:
    w = Work()
    w.doi = (msg.get("DOI") or "").lower() or None
    titles = msg.get("title") or []
    w.title = titles[0] if titles else None
    issued = msg.get("issued", {}).get("date-parts", [[None]])
    w.year = issued[0][0] if issued and issued[0] and issued[0][0] else None
    w.journal = (msg.get("container-title") or [None])[0]
    w.volume = msg.get("volume")
    w.issue = msg.get("issue")
    w.pages = msg.get("page")
    w.publisher = msg.get("publisher")
    w.authors = [
        {
            "family": a.get("family"),
            "given": a.get("given"),
            "orcid": (a.get("ORCID") or "").replace("http://orcid.org/", "") or None,
        }
        for a in (msg.get("author") or [])
    ]
    w.extra["crossref"] = {
        "license": [lic.get("URL") for lic in (msg.get("license") or [])],
        "links": [
            {
                "url": link.get("URL"),
                "type": link.get("content-type"),
                "intended": link.get("intended-application"),
            }
            for link in (msg.get("link") or [])
        ],
        "type": msg.get("type"),
    }
    return w


def _pubmed_to_work(doc: dict) -> Work:
    w = Work()
    w.pmid = doc.get("uid")
    w.title = (doc.get("title") or "").rstrip(".") or None
    pubdate = doc.get("pubdate") or doc.get("epubdate") or ""
    import re as _re
    m = _re.search(r"\d{4}", pubdate)
    w.year = int(m.group(0)) if m else None
    w.journal = doc.get("fulljournalname") or doc.get("source")
    w.volume = doc.get("volume")
    w.issue = doc.get("issue")
    w.pages = doc.get("pages")
    w.authors = []
    for author in doc.get("authors") or []:
        if not author.get("name"):
            continue
        family, given = _author_parts(author["name"])
        w.authors.append({"family": family, "given": given, "orcid": None})
    ids = {a.get("idtype"): a.get("value") for a in (doc.get("articleids") or [])}
    w.doi = ids.get("doi", "").lower() or None
    w.pmcid = ids.get("pmc") or None
    return w


def _openalex_to_work(rec: dict) -> Work:
    w = Work()
    ids = rec.get("ids") or {}
    w.doi = (ids.get("doi") or "").replace("https://doi.org/", "").lower() or None
    w.pmid = (ids.get("pmid") or "").replace("https://pubmed.ncbi.nlm.nih.gov/", "") or None
    w.pmcid = (ids.get("pmcid") or "").replace("https://www.ncbi.nlm.nih.gov/pmc/articles/", "") or None
    w.title = rec.get("display_name")
    w.year = rec.get("publication_year")
    w.journal = (rec.get("primary_location") or {}).get("source", {}).get("display_name")
    w.publisher = (rec.get("primary_location") or {}).get("source", {}).get("publisher")
    w.authors = []
    for a in rec.get("authorships") or []:
        name = (a.get("author") or {}).get("display_name") or ""
        family, given = _author_parts(name)
        w.authors.append(
            {"family": family,
             "given": given,
             "orcid": (a.get("author") or {}).get("orcid")}
        )
    w.extra["openalex"] = {
        "is_oa": rec.get("open_access", {}).get("is_oa"),
        "oa_url": rec.get("open_access", {}).get("oa_url"),
        "type": rec.get("type"),
    }
    return w


def _datacite_to_work(data: dict) -> Work:
    attrs = data.get("attributes") or {}
    w = Work()
    w.doi = (attrs.get("doi") or "").lower() or None
    titles = attrs.get("titles") or []
    w.title = titles[0].get("title") if titles else None
    w.year = attrs.get("publicationYear")
    w.publisher = attrs.get("publisher")
    w.authors = [
        {
            "family": c.get("familyName") or c.get("name"),
            "given": c.get("givenName"),
            "orcid": None,
        }
        for c in attrs.get("creators") or []
    ]
    w.extra["datacite"] = {
        "type": (attrs.get("types") or {}).get("resourceTypeGeneral"),
        "url": attrs.get("url"),
    }
    return w


def merge_work(base: Work, incoming: Work) -> Work:
    for field in ("doi", "pmid", "pmcid", "arxiv", "title", "year", "journal",
                  "volume", "issue", "pages", "publisher"):
        if not getattr(base, field) and getattr(incoming, field):
            setattr(base, field, getattr(incoming, field))
    if not base.authors and incoming.authors:
        base.authors = incoming.authors
    for k, v in (incoming.extra or {}).items():
        base.extra[k] = v
    return base


async def resolve_by_doi(client: httpx.AsyncClient, doi: str) -> Work:
    try:
        data = await _get(client, f"{CROSSREF_BASE}/{doi}")
    except httpx.HTTPError:
        data = None
    if data:
        return _crossref_to_work(data.get("message", {}))
    try:
        data = await _get(client, f"{DATACITE_BASE}/{doi}")
    except httpx.HTTPError:
        data = None
    if data and data.get("data"):
        return _datacite_to_work(data["data"])
    try:
        data = await _get(client, f"{OPENALEX_BASE}/doi:{doi}")
    except httpx.HTTPError:
        data = None
    if data:
        return _openalex_to_work(data)
    raise ValueError(f"Crossref/DataCite/OpenAlex 均无记录: {doi}")


async def resolve_by_arxiv(client: httpx.AsyncClient, arxiv: str) -> Work:
    resp = await client.get(
        ARXIV_BASE, params={"id_list": arxiv}, headers=HEADERS, follow_redirects=True)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {"atom": "http://www.w3.org/2005/Atom",
          "arxiv": "http://arxiv.org/schemas/atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ValueError(f"arXiv 无记录: {arxiv}")
    w = Work(arxiv=arxiv)
    title = entry.findtext("atom:title", default="", namespaces=ns)
    w.title = " ".join(title.split()) or None
    published = entry.findtext("atom:published", default="", namespaces=ns)
    w.year = int(published[:4]) if published[:4].isdigit() else None
    w.doi = (entry.findtext("arxiv:doi", default="", namespaces=ns) or "").lower() or None
    w.authors = []
    for author in entry.findall("atom:author", ns):
        name = author.findtext("atom:name", default="", namespaces=ns)
        parts = name.rsplit(" ", 1)
        w.authors.append({
            "family": parts[-1] if parts else None,
            "given": parts[0] if len(parts) > 1 else None,
            "orcid": None,
        })
    w.extra["arxiv"] = {"pdf_url": f"https://arxiv.org/pdf/{arxiv}"}
    return w


async def resolve_by_pmid(client: httpx.AsyncClient, pmid: str) -> Work:
    url = (f"{EUTILS_BASE}/esummary.fcgi?db=pubmed&id={pmid}&retmode=json&tool=litlib&email={CONTACT_EMAIL}")
    data = await _get(client, url)
    if not data:
        raise ValueError(f"PubMed 无记录: {pmid}")
    docs = data.get("result", {})
    uid = docs.get("uids", [None])[0]
    if not uid:
        raise ValueError(f"PubMed 无记录: {pmid}")
    return _pubmed_to_work(docs[uid])


async def resolve_by_pmcid(client: httpx.AsyncClient, pmcid: str) -> Work:
    url = f"{EUROPE_PMC_BASE}/search?query=PMCID%3A{pmcid}&format=json"
    data = await _get(client, url)
    if not data:
        raise ValueError(f"Europe PMC 无记录: {pmcid}")
    results = data.get("resultList", {}).get("result", [])
    if not results:
        raise ValueError(f"Europe PMC 无记录: {pmcid}")
    r = results[0]
    w = Work()
    w.pmcid = r.get("pmcid")
    w.pmid = r.get("pmid")
    w.doi = (r.get("doi") or "").lower() or None
    w.title = r.get("title")
    if r.get("pubYear"):
        try:
            w.year = int(r["pubYear"])
        except (TypeError, ValueError):
            pass
    w.journal = r.get("journalTitle") or r.get("journalInfo", {}).get("journal", {}).get("title")
    w.authors = []
    for author in r.get("authorList", {}).get("author") or []:
        family, given = _author_parts(author.get("fullName") or "")
        w.authors.append({"family": family, "given": given, "orcid": None})
    return w


async def resolve_by_title_search(client: httpx.AsyncClient, work: Work) -> Work:
    q = httpx.URL(OPENALEX_BASE, params={"filter": f"title.search:{work.title}", "per-page": 3})
    data = await _get(client, str(q))
    if not data:
        return Work()
    for rec in data.get("results", []):
        if rec.get("title") and rec["title"].strip().lower() == work.title.strip().lower():
            return _openalex_to_work(rec)
    return Work()


async def fetch_metadata(client: httpx.AsyncClient, work: Work) -> Work:
    """按优先级解析元数据并合并；无结果返回空 Work。"""
    result = Work()
    if work.doi:
        try:
            result = merge_work(result, await resolve_by_doi(client, work.doi))
        except (httpx.HTTPError, ValueError):
            result = Work()
    if not result.title and work.pmid:
        try:
            result = merge_work(result, await resolve_by_pmid(client, work.pmid))
        except (httpx.HTTPError, ValueError):
            result = Work()
    if not result.title and work.pmcid:
        try:
            result = merge_work(result, await resolve_by_pmcid(client, work.pmcid))
        except (httpx.HTTPError, ValueError):
            result = Work()
    if not result.title and work.arxiv:
        try:
            result = merge_work(result, await resolve_by_arxiv(client, work.arxiv))
        except (httpx.HTTPError, ValueError, ET.ParseError):
            result = Work()
    if result.doi and not (result.pmid or result.pmcid):
        try:
            data = await _get(client, f"{OPENALEX_BASE}/doi:{result.doi}")
            if data:
                result = merge_work(result, _openalex_to_work(data))
        except (httpx.HTTPError, ValueError):
            pass
    if not result.title and work.title:
        found = await resolve_by_title_search(client, work)
        if found.title:
            result = merge_work(result, found)
    if result.title:
        result.work_id = work.work_id
        result.created_at = work.created_at
        result.updated_at = work.updated_at
        result.is_version_of = work.is_version_of
    return result
