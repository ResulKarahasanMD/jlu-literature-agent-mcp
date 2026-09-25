"""OA 通道：发现公开全文候选，下载阶段按候选逐一验证。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from litlib.models import Work, arxiv_id_from_doi

UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
CROSSREF_BASE = "https://api.crossref.org/works"
OPENALEX_BASE = "https://api.openalex.org/works"

CONTACT_EMAIL = os.environ.get("LITLIB_EMAIL", "litlib@example.invalid")
HEADERS = {"User-Agent": f"litlib/0.1 (mailto:{CONTACT_EMAIL})", "Accept": "application/json"}


@dataclass
class OAResult:
    found: bool
    url: str | None = None
    channel: str | None = None
    note: str | None = None


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


TDM_HOSTS = ("api.wiley.com", "api.elsevier.com", "onlinelibrary.wiley.com/action/download")
OPEN_LICENSE_MARKERS = (
    "creativecommons.org/", "creativecommons.net/", "publicdomain/",
    "creativecommons/publicdomain", "opensource.org/",
)


def _pick_pdf_url(links: list[dict]) -> str | None:
    usable = [
        link for link in links
        if link.get("intended-application") != "text-mining"
        and not any(host in (link.get("URL") or "") for host in TDM_HOSTS)
    ]
    if not usable:
        return None
    for link in usable:
        if link.get("intended-application") == "text/html":
            return link.get("URL")
    for link in usable:
        if link.get("content-type") in (None, "application/pdf", "application/octet-stream"):
            return link.get("URL")
    for link in usable:
        if link.get("URL"):
            return link.get("URL")
    return None


async def unpaywall(client: httpx.AsyncClient, work: Work) -> OAResult:
    if not work.doi:
        return OAResult(False, note="无 DOI")
    email = os.environ.get("LITLIB_EMAIL", "litlib@example.invalid")
    if email.endswith("invalid"):
        return OAResult(False, note="未配置 LITLIB_EMAIL，跳过 Unpaywall")
    data = await _get(client, f"{UNPAYWALL_BASE}/{work.doi}?email={email}")
    if not data or not data.get("is_oa"):
        return OAResult(False, note="Unpaywall 非 OA")
    loc = data.get("best_oa_location") or {}
    url = loc.get("url_for_pdf") or loc.get("url")
    if not url:
        return OAResult(False, note="Unpaywall 无可用链接")
    return OAResult(True, url=url, channel="unpaywall")


async def arxiv_direct(client: httpx.AsyncClient, work: Work) -> OAResult:
    arxiv = work.arxiv or arxiv_id_from_doi(work.doi)
    if not arxiv:
        return OAResult(False, note="无 arXiv ID")
    return OAResult(True, url=f"https://arxiv.org/pdf/{arxiv}", channel="arxiv")


async def mdpi_static_pdf(client: httpx.AsyncClient, work: Work) -> OAResult:
    """构造 MDPI 公开静态 PDF，绕过主站 HTML 风控页。"""
    if not work.doi or not work.doi.lower().startswith("10.3390/"):
        return OAResult(False, note="非 MDPI DOI")
    match = re.fullmatch(r"10\.3390/([a-z]+)(\d{2})(\d{2})(\d+)", work.doi.lower())
    if not match:
        return OAResult(False, note="MDPI DOI 格式未识别")
    prefix, volume, _issue, article = match.groups()
    slug = {"antib": "antibodies", "biom": "biomolecules"}.get(prefix, prefix)
    filename = f"{slug}-{int(volume):02d}-{int(article):05d}.pdf"
    url = f"https://mdpi-res.com/d_attachment/{slug}/{filename[:-4]}/article_deploy/{filename}"
    return OAResult(True, url=url, channel="mdpi_static")


async def europe_pmc(client: httpx.AsyncClient, work: Work) -> OAResult:
    if not (work.pmcid or work.pmid):
        return OAResult(False, note="无 PMC/PMID")
    query = work.pmcid or f"PMID:{work.pmid}"
    data = await _get(client, f"{EUROPE_PMC_BASE}/search?query={query}&format=json")
    results = (data or {}).get("resultList", {}).get("result", [])
    if not results:
        return OAResult(False, note="Europe PMC 无记录")
    r = results[0]
    if r.get("isOpenAccess") != "Y":
        return OAResult(False, note="Europe PMC 非开放")
    if r.get("pmcid"):
        url = f"https://europepmc.org/articles/{r['pmcid']}?pdf=render"
    else:
        url = f"{EUROPE_PMC_BASE}/{r['source']}/{r['id']}/fullTextPDF"
    return OAResult(True, url=url, channel="europe_pmc")


async def crossref_link(client: httpx.AsyncClient, work: Work) -> OAResult:
    if not work.doi:
        return OAResult(False, note="无 DOI")
    data = await _get(client, f"{CROSSREF_BASE}/{work.doi}")
    msg = (data or {}).get("message", {})
    licenses = [str(item.get("URL") or "").lower() for item in msg.get("license") or []]
    if not any(any(marker in url for marker in OPEN_LICENSE_MARKERS) for url in licenses):
        return OAResult(False, note="Crossref 链接未证明为 OA")
    url = _pick_pdf_url(msg.get("link") or [])
    if not url:
        return OAResult(False, note="Crossref 无链接")
    return OAResult(True, url=url, channel="crossref_link")


async def openalex_oa(client: httpx.AsyncClient, work: Work) -> OAResult:
    if not work.doi:
        return OAResult(False, note="无 DOI")
    data = await _get(client, f"{OPENALEX_BASE}/doi:{work.doi}")
    if not data:
        return OAResult(False, note="OpenAlex 无记录")
    oa = data.get("open_access") or {}
    candidates = []
    # Direct PDF locations precede landing pages.
    for loc in data.get("locations") or []:
        if loc.get("is_oa") and loc.get("pdf_url"):
            candidates.append(loc["pdf_url"])
    if oa.get("is_oa") and oa.get("oa_url"):
        candidates.append(oa["oa_url"])
    for loc in data.get("locations") or []:
        if loc.get("is_oa") and loc.get("landing_page_url"):
            candidates.append(loc["landing_page_url"])
    for url in candidates:
        if url:
            return OAResult(True, url=url, channel="openalex")
    return OAResult(False, note="OpenAlex 非 OA")


async def find_oa(client: httpx.AsyncClient, work: Work) -> OAResult:
    candidates = await find_oa_candidates(client, work)
    if candidates:
        return candidates[0]
    return OAResult(False, note="所有 OA 通道均未命中")


async def find_oa_candidates(client: httpx.AsyncClient, work: Work) -> list[OAResult]:
    """返回去重后的 OA 候选；单个 provider 故障不阻断后续 provider。"""
    candidates: list[OAResult] = []
    seen: set[str] = set()
    for fn in (arxiv_direct, mdpi_static_pdf, unpaywall, europe_pmc, openalex_oa, crossref_link):
        try:
            result = await fn(client, work)
        except (httpx.HTTPError, ValueError):
            continue
        if not result.found or not result.url or result.url in seen:
            continue
        seen.add(result.url)
        candidates.append(result)
    return candidates
