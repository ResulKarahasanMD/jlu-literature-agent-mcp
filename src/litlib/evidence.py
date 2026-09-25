"""Enzim verisi çıkarımı için kanıt ön değerlendirmesi.

Bu modül bir makalenin eksiksiz ölçüm içerdiğini iddia etmez. Olası kanıtın nerede
bulunduğunu ve hangi hedef alanların hâlâ incelenmesi gerektiğini raporlar.
"""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

FIELD_PATTERNS = {
    "activity": re.compile(r"\b(?:enzyme\s+)?activity|specific\s+activity|U\s*/\s*(?:mL|mg)", re.I),
    "kinetics": re.compile(r"\b(?:K\s*m|k\s*cat|V\s*max|catalytic\s+efficiency)\b", re.I),
    "temperature": re.compile(r"\b(?:temperature|\bdeg\s*C|\b\d+\s*°?C)\b", re.I),
    "ph": re.compile(r"\bpH\b", re.I),
    "substrate": re.compile(r"\b(?:substrate|CMC|Avicel|PASC|cellobiose|cellulose)\b", re.I),
    "sequence": re.compile(r"\b(?:UniProt|GenBank|accession|sequence|mutant|truncat)\b", re.I),
}

SUPPLEMENT_PATTERNS = (
    re.compile(r"supplement(?:ary|al)?", re.I),
    re.compile(r"supporting\s+(?:information|data|material)", re.I),
    re.compile(r"source\s+data", re.I),
    re.compile(r"additional\s+file", re.I),
)
FIGURE_PATTERN = re.compile(r"\b(?:fig(?:ure)?|panel)\.?\s*[A-Z]?\d+", re.I)
TABLE_PATTERN = re.compile(r"\btable\s*[A-Z]?\d+", re.I)


def _page_excerpt(text: str, pattern: re.Pattern[str], limit: int = 240) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    start = max(0, match.start() - 80)
    return " ".join(text[start:start + limit].split())


def scan_pdf_evidence(path: Path | str, max_excerpt_per_field: int = 3) -> dict:
    """Aranabilir PDF metnini tarar ve bir ön değerlendirme manifesti döndürür.

    Sonuç bilerek temkinlidir: ``needs_figure_review``, olası bir görsel/tablo kanıt
    yolu olduğunu anlatır; bir VLM çağrılması gerektiğini değil.
    """
    pdf_path = Path(path)
    reader = PdfReader(str(pdf_path), strict=False)
    pages = [page.extract_text() or "" for page in reader.pages]
    joined = "\n".join(pages)
    field_pages: dict[str, list[int]] = {}
    excerpts: dict[str, list[str]] = {}
    for field, pattern in FIELD_PATTERNS.items():
        hits = [i + 1 for i, text in enumerate(pages) if pattern.search(text)]
        field_pages[field] = hits
        excerpts[field] = [
            excerpt for text in pages
            if (excerpt := _page_excerpt(text, pattern))
        ][:max_excerpt_per_field]

    supplement_pages = [
        i + 1 for i, text in enumerate(pages)
        if any(pattern.search(text) for pattern in SUPPLEMENT_PATTERNS)
    ]
    figure_pages = [i + 1 for i, text in enumerate(pages) if FIGURE_PATTERN.search(text)]
    table_pages = [i + 1 for i, text in enumerate(pages) if TABLE_PATTERN.search(text)]
    missing_fields = [field for field, hits in field_pages.items() if not hits]
    has_supplement_reference = bool(supplement_pages)
    has_visual_reference = bool(figure_pages or table_pages)
    missing_measurement = not field_pages["activity"] and not field_pages["kinetics"]
    missing_condition = any(
        not field_pages[field] for field in ("temperature", "ph", "substrate")
    )
    image_review_pages = sorted(set(figure_pages + table_pages)) if (
        has_visual_reference and (missing_measurement or missing_condition)
    ) else []
    return {
        "path": str(pdf_path),
        "pages": len(pages),
        "text_chars": len(joined),
        "field_pages": field_pages,
        "field_excerpts": excerpts,
        "supplement_reference_pages": supplement_pages,
        "figure_pages": figure_pages,
        "table_pages": table_pages,
        "missing_fields": missing_fields,
        "measurement_evidence_available": not missing_measurement,
        "needs_supplement_review": has_supplement_reference,
        "needs_figure_review": bool(image_review_pages),
        "image_review_pages": image_review_pages,
        "triage_status": "text_evidence_available" if not missing_fields else "review_required",
    }
