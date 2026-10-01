"""İsteğe bağlı tam metin: Zotero eki → sayfalı tam metin, önbellekli (§16, §27.9)."""

from __future__ import annotations

import json
from pathlib import Path

from litlib.config import paths
from litlib.models import sha256_of_file
from litlib.pdf import PDFError, validate_pdf

PIPELINE_VERSION = 1
DEFAULT_LIMIT_CHARS = 10_000
MAX_LIMIT_CHARS = 20_000

_cache_root = paths.output / "fulltext"


def cache_path(attachment_key: str, sha: str) -> Path:
    return _cache_root / f"{attachment_key}.{sha[:16]}.v{PIPELINE_VERSION}.json"


def _load_cache(cp: Path) -> str | None:
    if not cp.exists():
        return None
    try:
        data = json.loads(cp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data.get("text") if data.get("pipeline_version") == PIPELINE_VERSION else None


def get_fulltext(pdf_path: Path, attachment_key: str, offset: int = 0,
                 limit_chars: int = DEFAULT_LIMIT_CHARS, *, cache: bool = True) -> dict:
    """{total_chars, offset, limit_chars, text, from_cache} döndürür."""
    limit_chars = max(1, min(limit_chars, MAX_LIMIT_CHARS))
    sha = sha256_of_file(pdf_path) if cache else ""
    cp = cache_path(attachment_key, sha) if cache else None
    if cache:
        _cache_root.mkdir(parents=True, exist_ok=True)
    text = _load_cache(cp) if cp else None
    from_cache = text is not None
    if text is None:
        n_pages, n_chars = validate_pdf(pdf_path)
        if n_chars == 0:
            raise PDFError("PDF'te metin katmanı yok (OCR gerekir, Phase 7)")
        from pypdf import PdfReader

        parts: list[str] = []
        reader = PdfReader(str(pdf_path), strict=False)
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts)
        if cp:
            cp.write_text(
                json.dumps({"pipeline_version": PIPELINE_VERSION, "sha256": sha, "text": text},
                            ensure_ascii=False),
                encoding="utf-8",
            )
    total = len(text)
    return {
        "total_chars": total,
        "offset": offset,
        "limit_chars": limit_chars,
        "text": text[offset:offset + limit_chars],
        "from_cache": from_cache,
    }
