"""PDF identity validation and text extraction with pypdf."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from litlib.models import normalize_doi


class PDFError(Exception):
    pass


_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.I)
_SUPPLEMENT_RE = re.compile(
    r"^\s*(supplementary|supporting)\s+(materials?|information|data)|"
    r"^\s*reporting\s+summary",
    re.I | re.M,
)


def _doi_in_text(doi: str, text: str) -> bool:
    """匹配 DOI 本身，允许 PDF 文本提取在 DOI 内插入换行。"""
    pattern = r"\s*".join(re.escape(char) for char in doi)
    return bool(re.search(pattern, text, re.I))


def validate_pdf(path: Path | str) -> tuple[int, int]:
    """校验 PDF，返回 (页数, 文本字符数)。非法文件抛 PDFError。"""
    p = Path(path)
    if not p.exists():
        raise PDFError(f"文件不存在: {p}")
    with open(p, "rb") as f:
        if f.read(5) != b"%PDF-":
            raise PDFError(f"非 PDF 文件头: {p}")
        size = p.stat().st_size
        f.seek(max(0, size - 16_384))
        if b"%%EOF" not in f.read():
            raise PDFError(f"PDF 文件尾缺少 %%EOF，文件可能被截断: {p}")
    try:
        reader = PdfReader(str(p), strict=False)
        n_pages = len(reader.pages)
        if n_pages < 1:
            raise PDFError("PDF 无页面")
        chars = sum(len(page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        raise PDFError(f"PDF 解析失败: {e}") from e
    return n_pages, chars


def validate_pdf_for_work(path: Path | str, doi: str | None = None) -> tuple[int, int]:
    """校验 PDF，并拒绝明显的补充材料或属于其他 DOI 的正文。"""
    p = Path(path)
    n_pages, chars = validate_pdf(p)
    if p.stat().st_size < 5_000:
        raise PDFError(f"PDF 文件过小: {p.stat().st_size}B")
    try:
        reader = PdfReader(str(p), strict=False)
        page_texts = [page.extract_text() or "" for page in reader.pages]
        first_page_text = page_texts[0] if page_texts else ""
        first_text = "\n".join(page_texts[:3])
        searchable_text = "\n".join(page_texts)
    except Exception as e:
        raise PDFError(f"PDF 文本校验失败: {e}") from e

    if _SUPPLEMENT_RE.search(first_text[:5_000]):
        raise PDFError("检测到补充材料，不是正文 PDF")
    if doi:
        expected = normalize_doi(doi)
        first_page_found = {
            normalize_doi(match.group(0)) for match in _DOI_RE.finditer(first_page_text)
        }
        first_pages_found = {
            normalize_doi(match.group(0)) for match in _DOI_RE.finditer(first_text)
        }
        all_found = {
            normalize_doi(match.group(0)) for match in _DOI_RE.finditer(searchable_text)
        }
        expected_on_first_page = expected in first_page_found or _doi_in_text(
            expected, first_page_text
        )
        competing_first_page = {
            found for found in first_page_found
            if found != expected and not expected.startswith(found)
        }
        if competing_first_page or (first_page_found and not expected_on_first_page):
            found = ", ".join(sorted(competing_first_page or first_page_found)[:3])
            raise PDFError(f"PDF DOI 不匹配: 期望 {expected}，首页检测到 {found}")
        if expected not in first_pages_found and not _doi_in_text(expected, first_text):
            location = "仅在后文检测到" if expected in all_found or _doi_in_text(expected, searchable_text) else "实际"
            found = ", ".join(sorted(all_found)[:3]) or "未检测到 DOI"
            raise PDFError(f"PDF DOI 不匹配: 期望 {expected}，{location} {found}")
    return n_pages, chars
