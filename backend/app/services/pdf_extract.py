"""Recover text from an uploaded PDF.

Strategies:
  * text — PyMuPDF's text layer. Right answer when the PDF is Unicode-encoded.
  * ocr  — render the page at high DPI and read it with tesseract (guj+eng).
           Required for legacy-font PDFs (LMG/Saral-style Gujarati fonts whose
           text layer is ASCII gibberish like "J[RF6 N:TFJ[H") and for scans.

Upload marks pages that look legacy/scanned (`needs_ocr`) so the router can OCR
them in a background task. Both strategies emit the same simple HTML: <p>
paragraphs with lines joined (so text can *reflow*), centered headings as
<p class="text-center">, and dash separator lines as <hr>.
"""
import html
import io
import re

import fitz  # PyMuPDF

GUJARATI_RE = re.compile(r"[઀-૿]")
_RULE_CHARS = set("-—–―_=~·•.")


def _is_rule(text: str) -> bool:
    t = text.strip()
    return len(t) >= 6 and sum(c in _RULE_CHARS for c in t) / len(t) >= 0.8


def looks_legacy(text: str) -> bool:
    """Heuristic: is this page's text layer legacy-font gibberish (or absent)?

    Legacy Gujarati fonts map glyphs over ASCII, producing consonant-soup like
    "J[RF6 N:TFJ[H" — heavy on uppercase letters and bracket/backslash symbols,
    light on vowels, with no real Gujarati codepoints.
    """
    t = re.sub(r"\s+", "", text or "")
    if len(t) < 30:
        return True  # little/no text layer -> scanned or image-only page, OCR it
    if len(GUJARATI_RE.findall(t)) / len(t) > 0.10:
        return False  # already Unicode Gujarati
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return True
    vowel_ratio = sum(c in "aeiouAEIOU" for c in letters) / len(letters)
    upper_ratio = sum(c.isupper() for c in letters) / len(letters)
    weird_ratio = sum(c in "[]{}\\|~^<>@#$%&*=" for c in t) / len(t)
    return weird_ratio > 0.05 or (vowel_ratio < 0.28 and upper_ratio > 0.5)


def _centered(x0: float, x1: float, col_l: float, col_r: float) -> bool:
    w = col_r - col_l
    if w <= 0:
        return False
    return (x1 - x0) < 0.75 * w and abs((x0 + x1) / 2 - (col_l + col_r) / 2) < 0.06 * w


def _para_html(text: str, centered: bool) -> str:
    if _is_rule(text):
        return "<hr>"
    cls = ' class="text-center"' if centered else ""
    return f"<p{cls}>{html.escape(text)}</p>"


def extract_pages(pdf_bytes: bytes) -> list[dict]:
    """Return [{page_number, html, method, needs_ocr}] from the text layer.

    Lines within a block are joined into one paragraph — the original PDF's
    hard line breaks are an artifact of its fixed layout, and keeping them
    would break reflow (the whole point of the template).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages: list[dict] = []
        for i in range(doc.page_count):
            page = doc[i]
            # blocks: (x0, y0, x1, y1, text, block_no, block_type); type 0 == text.
            blocks = [b for b in page.get_text("blocks") if b[6] == 0]
            blocks.sort(key=lambda b: (round(b[1] / 3), b[0]))  # row-band, then left-to-right
            col_l = min((b[0] for b in blocks), default=0.0)
            col_r = max((b[2] for b in blocks), default=page.rect.width)
            parts: list[str] = []
            raw: list[str] = []
            for b in blocks:
                text = " ".join(ln.strip() for ln in b[4].splitlines() if ln.strip())
                if not text:
                    continue
                raw.append(text)
                parts.append(_para_html(text, _centered(b[0], b[2], col_l, col_r)))
            pages.append({
                "page_number": i + 1,
                "html": "\n".join(parts) or "<p></p>",
                "method": "text",
                "needs_ocr": 1 if looks_legacy(" ".join(raw)) else 0,
            })
        return pages
    finally:
        doc.close()


def page_count(pdf_bytes: bytes) -> int:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return doc.page_count
    finally:
        doc.close()


def _page_png(pdf_bytes: bytes, page_number: int, dpi: int) -> bytes:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if not (1 <= page_number <= doc.page_count):
            raise ValueError(f"page {page_number} out of range (1..{doc.page_count})")
        return doc[page_number - 1].get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()


def render_page_png(pdf_bytes: bytes, page_number: int, dpi: int = 130) -> bytes:
    """Original-page preview image for the side-by-side editor view."""
    return _page_png(pdf_bytes, page_number, dpi)


def ocr_page_html(pdf_bytes: bytes, page_number: int, langs: str = "guj+eng", dpi: int = 300) -> str:
    """OCR one page (1-indexed) into HTML: tables + paragraphs, in page order.

    Uses tesseract's word boxes (image_to_data) rather than plain text so we can
    rebuild whitespace-aligned tables (see table_detect), real paragraphs, and
    centered headings. Imports Pillow/pytesseract lazily so text-only extraction
    never needs them.
    """
    from PIL import Image
    import pytesseract
    from pytesseract import Output

    from . import table_detect

    img = Image.open(io.BytesIO(_page_png(pdf_bytes, page_number, dpi)))
    data = pytesseract.image_to_data(img, lang=langs, output_type=Output.DICT)

    words: list[dict] = []
    for i in range(len(data["text"])):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        words.append({
            "id": len(words),
            "block": data["block_num"][i],
            "par": data["par_num"][i],
            "line": data["line_num"][i],
            "txt": txt,
            "x0": data["left"][i],
            "y0": data["top"][i],
            "x1": data["left"][i] + data["width"][i],
            "y1": data["top"][i] + data["height"][i],
        })
    if not words:
        return "<p></p>"

    # Carve out whitespace-aligned tables first; never let detection kill a page.
    try:
        tables = table_detect.detect_tables(words)
    except Exception:
        tables = []
    consumed: set[int] = set()
    for t in tables:
        consumed |= t["ids"]
    elements: list[tuple[float, str]] = [(t["y0"], t["html"]) for t in tables]

    # Everything else flows as paragraphs (tesseract's block/par grouping).
    col_l = min(w["x0"] for w in words)
    col_r = max(w["x1"] for w in words)
    paras: dict[tuple, list[dict]] = {}
    for w in words:
        if w["id"] in consumed:
            continue
        paras.setdefault((w["block"], w["par"]), []).append(w)

    for ws in paras.values():
        lines: dict[int, list[dict]] = {}
        for w in ws:
            lines.setdefault(w["line"], []).append(w)
        text = " ".join(
            " ".join(w["txt"] for w in sorted(line, key=lambda w: w["x0"]))
            for line in sorted(lines.values(), key=lambda l: min(w["y0"] for w in l))
        )
        x0 = min(w["x0"] for w in ws)
        x1 = max(w["x1"] for w in ws)
        y0 = min(w["y0"] for w in ws)
        elements.append((y0, _para_html(text, _centered(x0, x1, col_l, col_r))))

    elements.sort(key=lambda e: e[0])
    return "\n".join(h for _, h in elements)
