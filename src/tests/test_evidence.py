from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen import canvas

from litlib.evidence import scan_pdf_evidence
from litlib.supplements import discover_supplement_candidates, validate_supplement


def make_pdf(path: Path, pages: list[str]) -> Path:
    document = canvas.Canvas(str(path))
    for text in pages:
        document.drawString(72, 740, text)
        document.showPage()
    document.save()
    return path


def test_scan_pdf_reports_fields_and_review_queues(tmp_path: Path):
    path = make_pdf(
        tmp_path / "paper.pdf",
        [
            "Enzyme activity was measured on CMC at pH 5 and 50 C.",
            "See Supplementary Table S1 and Figure 2 for kinetics.",
        ],
    )
    result = scan_pdf_evidence(path)
    assert result["field_pages"]["activity"] == [1]
    assert result["field_pages"]["substrate"] == [1]
    assert result["needs_supplement_review"] is True
    assert result["figure_pages"] == [2]
    assert result["table_pages"] == [2]
    assert result["measurement_evidence_available"] is True
    assert result["needs_figure_review"] is False


def test_discover_supplement_candidates_resolves_links():
    html = """
    <a href="/files/supp_table.xlsx?token=secret">Supplementary Table S1</a>
    <a href="/article">Article</a>
    <a href="/files/source-data.csv">Source Data</a>
    """
    candidates = discover_supplement_candidates(html, "https://example.org/article")
    assert len(candidates) == 2
    assert candidates[0].url.startswith("https://example.org/files/supp_table.xlsx")
    assert "token=secret" in candidates[0].url
    assert "token=secret" not in candidates[0].safe_dict()["url"]


def test_validate_supplement_pdf(tmp_path: Path):
    path = make_pdf(tmp_path / "supp.pdf", ["Supplementary data"])
    result = validate_supplement(path, "application/pdf")
    assert result["artifact_type"] == "pdf"
    assert result["pages"] == 1
    assert len(result["sha256"]) == 64
