from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from litlib.pdf import PDFError, validate_pdf_for_work


def _pdf(path: Path, text: str) -> Path:
    document = canvas.Canvas(str(path))
    for page_text in text.split("\f"):
        y = 760
        for line in page_text.splitlines() or [""]:
            document.drawString(72, y, line)
            y -= 16
        document.showPage()
    document.save()
    # Work düzeyindeki asgari boyut korumasının bu kimlik testlerini bastırmamasını sağlar.
    with path.open("ab") as f:
        f.write(b" " * 5_000)
    return path


def test_rejects_supplementary_material(tmp_path: Path):
    path = _pdf(tmp_path / "supp.pdf", "Supplementary Materials for DOI 10.1000/right")
    with pytest.raises(PDFError, match="ek materyal algılandı"):
        validate_pdf_for_work(path, "10.1000/right")


def test_rejects_mismatched_doi(tmp_path: Path):
    path = _pdf(tmp_path / "wrong.pdf", "Research Article DOI: 10.1000/wrong")
    with pytest.raises(PDFError, match="PDF DOI uyuşmuyor"):
        validate_pdf_for_work(path, "10.1000/right")


def test_accepts_matching_doi(tmp_path: Path):
    path = _pdf(tmp_path / "right.pdf", "Research Article DOI: 10.1000/right")
    pages, chars = validate_pdf_for_work(path, "10.1000/right")
    assert pages == 1 and chars > 0


def test_accepts_doi_split_across_lines(tmp_path: Path):
    path = _pdf(tmp_path / "split.pdf", "Research Article DOI: 10.1146/annurev-animal-070722-\n084803")
    pages, chars = validate_pdf_for_work(path, "10.1146/annurev-animal-070722-084803")
    assert pages == 1 and chars > 0


def test_rejects_pdf_without_expected_doi(tmp_path: Path):
    path = _pdf(tmp_path / "missing-doi.pdf", "Research article without an identifier")
    with pytest.raises(PDFError, match="PDF DOI uyuşmuyor"):
        validate_pdf_for_work(path, "10.1000/right")


def test_rejects_truncated_pdf_without_eof(tmp_path: Path):
    path = tmp_path / "truncated.pdf"
    path.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n")
    with pytest.raises(PDFError, match="%%EOF"):
        validate_pdf_for_work(path, "10.1000/right")


def test_rejects_wrong_article_that_cites_target_later(tmp_path: Path):
    path = _pdf(
        tmp_path / "wrong-with-reference.pdf",
        "Research Article DOI: 10.1000/wrong\fReferences include DOI 10.1000/right",
    )
    with pytest.raises(PDFError, match="ilk sayfada algılanan"):
        validate_pdf_for_work(path, "10.1000/right")


def test_rejects_competing_doi_even_when_target_is_on_first_page(tmp_path: Path):
    path = _pdf(
        tmp_path / "two-dois.pdf",
        "Research Article DOI: 10.1000/wrong\nRelated DOI: 10.1000/right",
    )
    with pytest.raises(PDFError, match="ilk sayfada algılanan"):
        validate_pdf_for_work(path, "10.1000/right")


def test_rejects_supplement_label_later_on_first_pages(tmp_path: Path):
    padding = "ordinary text\n" * 40
    path = _pdf(
        tmp_path / "late-supplement.pdf",
        f"{padding}Supplementary Information\nDOI 10.1000/right",
    )
    with pytest.raises(PDFError, match="ek materyal algılandı"):
        validate_pdf_for_work(path, "10.1000/right")


def test_accepts_arxiv_doi_via_arxiv_stamp(tmp_path: Path):
    path = _pdf(tmp_path / "arxiv.pdf", "Attention Is All You Need\narXiv:1706.03762v7 [cs.CL] 2 Aug 2023")
    pages, chars = validate_pdf_for_work(path, "10.48550/arXiv.1706.03762")
    assert pages == 1 and chars > 0


def test_rejects_arxiv_doi_with_other_arxiv_stamp(tmp_path: Path):
    path = _pdf(tmp_path / "arxiv-wrong.pdf", "Another Paper\narXiv:1706.037621v1 [cs.CL] 1 Jan 2024")
    with pytest.raises(PDFError, match="PDF DOI uyuşmuyor"):
        validate_pdf_for_work(path, "10.48550/arXiv.1706.03762")
