"""Ek araştırma dosyalarını bulur, indirir ve doğrular."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader

from litlib.config import ensure_storage_path, paths
from litlib.download import download_to_file
from litlib.logging_setup import sanitize
from litlib.models import sha256_of_file

SUPPLEMENT_MARKERS = re.compile(
    r"supplement(?:ary|al)?|supporting|source\s*data|additional\s*file|si\b",
    re.I,
)
ALLOWED_SUFFIXES = {".pdf", ".xlsx", ".xls", ".csv", ".zip"}


@dataclass
class SupplementCandidate:
    url: str
    label: str
    media_type: str = ""
    source: str = "article_page"

    def safe_dict(self) -> dict:
        """Dışa açık gösterim; imzalı query içeriği asla yazdırılmaz."""
        return {
            "url": sanitize(self.url),
            "label": self.label,
            "media_type": self.media_type,
            "source": self.source,
        }


def discover_supplement_candidates(
    html: str,
    article_url: str,
) -> list[SupplementCandidate]:
    """bs4 gerektirmeden makale HTML'inden olası ek dosya bağlantılarını çıkarır."""
    link_re = re.compile(
        r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S
    )
    seen: set[str] = set()
    candidates: list[SupplementCandidate] = []
    for href, raw_label in link_re.findall(html):
        label = " ".join(re.sub(r"<[^>]+>", " ", raw_label).split())
        absolute = urljoin(article_url, href)
        path = urlparse(absolute).path.lower()
        if not SUPPLEMENT_MARKERS.search(f"{label} {path}"):
            continue
        suffix = Path(path).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES and "download" not in path:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        candidates.append(SupplementCandidate(absolute, label or Path(path).name))
    return candidates


def validate_supplement(path: Path | str, media_type: str = "") -> dict:
    """Desteklenen dosya imzalarını doğrular; ek PDF'lerin DOI içermesi gerekmez."""
    artifact = Path(path)
    if not artifact.exists() or artifact.stat().st_size == 0:
        raise ValueError(f"ek dosya yok ya da boş: {artifact}")
    suffix = artifact.suffix.lower()
    with artifact.open("rb") as handle:
        head = handle.read(8)
    if suffix == ".pdf" or "pdf" in media_type.lower():
        if not head.startswith(b"%PDF-"):
            raise ValueError("ek dosya PDF değil")
        with artifact.open("rb") as handle:
            handle.seek(max(0, artifact.stat().st_size - 16_384))
            tail = handle.read()
        if b"%%EOF" not in tail:
            raise ValueError("ek PDF'te %%EOF yok")
        pages = len(PdfReader(str(artifact), strict=False).pages)
        if pages < 1:
            raise ValueError("ek PDF'te sayfa yok")
        kind = "pdf"
        page_count = pages
    elif suffix in {".xlsx", ".xls", ".zip"} or head.startswith(b"PK") or head[:4] == b"\xD0\xCF\x11\xE0":
        kind = "archive_or_spreadsheet"
        page_count = None
    elif suffix == ".csv" or _looks_like_text(artifact):
        kind = "csv_or_text"
        page_count = None
    else:
        raise ValueError(f"desteklenmeyen ek dosya biçimi: {artifact.suffix}")
    return {
        "path": str(artifact),
        "artifact_type": kind,
        "media_type": media_type,
        "size_bytes": artifact.stat().st_size,
        "sha256": sha256_of_file(artifact),
        "pages": page_count,
    }


def _looks_like_text(path: Path) -> bool:
    with path.open("rb") as handle:
        sample = handle.read(4096)
    return b"\n" in sample and b"\x00" not in sample


async def discover_supplements_from_page(
    client: httpx.AsyncClient,
    article_url: str,
) -> list[SupplementCandidate]:
    response = await client.get(article_url, follow_redirects=True)
    response.raise_for_status()
    return discover_supplement_candidates(response.text, str(response.url))


async def download_supplement(
    client: httpx.AsyncClient,
    candidate: SupplementCandidate,
    dest: Path,
    *,
    parent_doi: str = "",
    overwrite: bool = False,
    max_bytes: int = 500 * 1024 * 1024,
) -> dict:
    """Tek bir ek dosyayı indirip doğrular; maskelenmiş bir manifest kaydı ekler."""
    ensure_storage_path(dest)
    if dest.exists() and not overwrite:
        raise FileExistsError(f"hedef dosya zaten var, üzerine yazılmadı: {dest}")
    _, digest, size = await download_to_file(client, candidate.url, dest, max_bytes=max_bytes)
    validation = validate_supplement(dest, candidate.media_type)
    record = {
        "parent_doi": parent_doi,
        "filename": dest.name,
        "artifact_type": validation["artifact_type"],
        "media_type": candidate.media_type,
        "source_url": sanitize(candidate.url),
        "label": candidate.label,
        "sha256": digest,
        "size_bytes": size,
        "pages": validation["pages"],
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "verified",
    }
    _append_manifest(record)
    return record


def _append_manifest(record: dict) -> None:
    paths.output.mkdir(parents=True, exist_ok=True)
    manifest = paths.output / "supplement_manifest.jsonl"
    ensure_storage_path(manifest)
    with manifest.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_manifest() -> list[dict]:
    manifest = paths.output / "supplement_manifest.jsonl"
    if not manifest.exists():
        return []
    records = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
