"""Veri modelleri: work_id, görev durum makinesi, tekilleştirme anahtarları."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class TaskState(StrEnum):
    QUEUED = "QUEUED"
    METADATA_FETCH = "METADATA_FETCH"
    DEDUPED = "DEDUPED"
    OA_OK = "OA_OK"
    REQUIRES_INST = "REQUIRES_INST"
    INST_QUEUED = "INST_QUEUED"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    PAYWALLED = "PAYWALLED"
    READY = "READY"
    PROPOSAL_GENERATED = "PROPOSAL_GENERATED"
    USER_REVIEWED = "USER_REVIEWED"
    IMPORTED = "IMPORTED"
    FAILED = "FAILED"


ALLOWED_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.QUEUED: {TaskState.METADATA_FETCH, TaskState.FAILED},
    TaskState.METADATA_FETCH: {TaskState.DEDUPED, TaskState.FAILED},
    TaskState.DEDUPED: {TaskState.OA_OK, TaskState.REQUIRES_INST, TaskState.FAILED},
    TaskState.OA_OK: {TaskState.DOWNLOADING, TaskState.REQUIRES_INST, TaskState.FAILED},
    TaskState.REQUIRES_INST: {TaskState.INST_QUEUED, TaskState.PAYWALLED, TaskState.FAILED},
    TaskState.INST_QUEUED: {TaskState.DOWNLOADING, TaskState.FAILED},
    TaskState.DOWNLOADING: {TaskState.VERIFYING, TaskState.REQUIRES_INST, TaskState.HUMAN_REQUIRED, TaskState.RATE_LIMITED, TaskState.PAYWALLED, TaskState.FAILED},
    TaskState.VERIFYING: {TaskState.READY, TaskState.REQUIRES_INST, TaskState.HUMAN_REQUIRED, TaskState.RATE_LIMITED, TaskState.PAYWALLED, TaskState.FAILED},
    TaskState.HUMAN_REQUIRED: {TaskState.QUEUED, TaskState.FAILED},
    TaskState.RATE_LIMITED: {TaskState.QUEUED, TaskState.FAILED},
    TaskState.PAYWALLED: set(),
    TaskState.READY: {TaskState.PROPOSAL_GENERATED, TaskState.FAILED},
    TaskState.PROPOSAL_GENERATED: {TaskState.USER_REVIEWED, TaskState.FAILED},
    TaskState.USER_REVIEWED: {TaskState.IMPORTED, TaskState.FAILED},
    TaskState.IMPORTED: set(),
    TaskState.FAILED: {TaskState.QUEUED},
}

DEDUPE_KEY_ORDER = ("doi", "pmid", "pmcid", "arxiv", "sha256", "title_year_author")

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.I)
_ARXIV_RE = re.compile(r"\d{4}\.\d{4,5}")
_PMID_RE = re.compile(r"\d{6,9}")
_PMC_RE = re.compile(r"PMC\d+", re.I)
_ARXIV_DOI_RE = re.compile(r"10\.48550/arxiv\.(.+)")


def normalize_doi(value: str) -> str:
    """Yaygın DOI giriş biçimlerini DOI'nin iç karakterlerine dokunmadan normalleştirir."""
    value = value.strip().strip('"').strip("'")
    value = re.sub(r"^doi\s*:\s*", "", value, flags=re.I)
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    return value.rstrip(".,;").lower()


def arxiv_id_from_doi(doi: str | None) -> str | None:
    """arXiv'in DataCite DOI'si (10.48550/arXiv.<id>) → arXiv ID; diğer DOI'lerde None döndürür."""
    if not doi:
        return None
    m = _ARXIV_DOI_RE.fullmatch(normalize_doi(doi))
    return m.group(1) if m else None


def normalize_identity_text(value: str) -> str:
    """Başlık/yazar kimlik anahtarları için Unicode güvenli normalleştirme."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in normalized if char.isalnum())


class Work(BaseModel):
    work_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    arxiv: str | None = None
    title: str | None = None
    year: int | None = None
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    authors: list[dict] = Field(default_factory=list)
    publisher: str | None = None
    is_version_of: str | None = None
    extra: dict = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


def parse_input_line(line: str) -> tuple[str, str] | None:
    """Giriş satırından (kind, value) tanır. kind ∈ doi/pmid/pmcid/arxiv/title."""
    s = line.strip().strip('"')
    if not s:
        return None
    if re.match(r"^(doi|input|id|title)\s*,", s, re.I):
        return None
    up = s.upper()
    for prefix, kind in (("DOI:", "doi"), ("PMID:", "pmid"), ("PMCID:", "pmcid"), ("ARXIV:", "arxiv")):
        if prefix in up:
            value = s.split(":", 1)[1].strip()
            return (kind, normalize_doi(value) if kind == "doi" else value)
    doi = normalize_doi(s)
    if _DOI_RE.fullmatch(doi):
        return ("doi", doi)
    if _PMC_RE.fullmatch(s):
        return ("pmcid", up)
    if _ARXIV_RE.fullmatch(s):
        return ("arxiv", s)
    if _PMID_RE.fullmatch(s):
        return ("pmid", s)
    return ("title", s)


def dedupe_keys_for(work: Work, pdf_sha256: str | None = None) -> dict[str, str]:
    """Bu work için kullanılabilir tekilleştirme anahtarlarını döndürür (yalnız boş olmayan değerler)."""
    keys: dict[str, str] = {}
    if work.doi:
        keys["doi"] = normalize_doi(work.doi)
    if work.pmid:
        keys["pmid"] = work.pmid
    if work.pmcid:
        keys["pmcid"] = work.pmcid.upper()
    if work.arxiv:
        keys["arxiv"] = work.arxiv
    if pdf_sha256:
        keys["sha256"] = pdf_sha256
    tya = title_year_author_key(work)
    if tya:
        keys["title_year_author"] = tya
    return keys


def title_year_author_key(work: Work) -> str | None:
    if not work.title or not work.year:
        return None
    first_author = ""
    if work.authors:
        first_author = work.authors[0].get("family") or ""
    if not first_author:
        return None
    title = normalize_identity_text(work.title)
    author = normalize_identity_text(first_author)
    if not title or not author:
        return None
    return f"{title}|{work.year}|{author}"


def sha256_of_file(path: Path | str, chunk_size: int = 1 << 20) -> str:
    """Akışlı SHA-256; dosyanın tamamını belleğe okumaz."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def transition_allowed(from_state: TaskState, to_state: TaskState) -> bool:
    return to_state in ALLOWED_TRANSITIONS.get(from_state, set())
