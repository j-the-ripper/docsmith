"""Recover text from an uploaded PDF.

Two document classes, two strategies:

  * rich text-layer (Unicode PDFs — resumes, contracts typed in real fonts):
    PyMuPDF's span dump carries font, size, bold/italic flags, color and exact
    boxes. We keep the styling: <b>/<i>, headings from size jumps, bullet lines
    as real <ul><li>, centered/right alignment, and same-line left|right pairs.

  * ocr (legacy-font PDFs whose text layer is ASCII gibberish like
    "J[RF6 N:TFJ[H", and scans): render the page at high DPI and read it with
    tesseract (guj+eng). Structure is inferred from word geometry; styling is
    added manually in the editor.

Upload marks pages that look legacy/scanned (`needs_ocr`) so the router can OCR
them in a background task. Both strategies emit flowing semantic HTML — lines
joined into paragraphs so text can *reflow*; coordinates are used to infer
structure, then discarded.
"""
import html
import io
import re

import fitz  # PyMuPDF

GUJARATI_RE = re.compile(r"[઀-૿]")
_RULE_CHARS = set("-—–―_=~·•.")

_BULLET_LEADERS = set("•●○◦▪■‣∙·*")
_DASH_LEADERS = set("–—-")

_FLAG_SUPERSCRIPT = 1
_FLAG_ITALIC = 2
_FLAG_BOLD = 16


def _is_rule(text: str) -> bool:
    t = text.strip()
    return len(t) >= 6 and sum(c in _RULE_CHARS for c in t) / len(t) >= 0.8


def looks_legacy(text: str) -> bool:
    """Heuristic: is this page's text layer legacy-font gibberish (or absent)?

    Legacy Gujarati fonts map glyphs over ASCII, producing consonant-soup like
    "J[RF6 N:TFJ[H" — almost no vowels, heavy uppercase, bracket/backslash
    symbols *inside words*. Crucially, symbol density alone is NOT a signal:
    real English documents are full of | % & separators. Only distrust the text
    layer when the letters themselves don't look like language.
    """
    t = re.sub(r"\s+", "", text or "")
    if len(t) < 30:
        return True  # little/no text layer -> scanned or image-only page, OCR it
    if len(GUJARATI_RE.findall(t)) / len(t) > 0.10:
        return False  # already Unicode Gujarati
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 15:
        return True  # no meaningful alphabetic content -> treat as scan
    vowel_ratio = sum(c in "aeiouAEIOU" for c in letters) / len(letters)
    upper_ratio = sum(c.isupper() for c in letters) / len(letters)
    weird_ratio = sum(c in "[]{}\\|~^<>@#$%&*=" for c in t) / len(t)
    # Real language keeps vowels; gibberish must ALSO look structurally broken.
    return vowel_ratio < 0.28 and (upper_ratio > 0.5 or weird_ratio > 0.03)


def _centered(x0: float, x1: float, col_l: float, col_r: float) -> bool:
    w = col_r - col_l
    if w <= 0:
        return False
    return (x1 - x0) < 0.75 * w and abs((x0 + x1) / 2 - (col_l + col_r) / 2) < 0.06 * w


def _right_aligned(x0: float, x1: float, col_l: float, col_r: float) -> bool:
    w = col_r - col_l
    if w <= 0:
        return False
    return (col_r - x1) < 0.04 * w and (x0 - col_l) > 0.35 * w


def _para_html(text: str, centered: bool) -> str:
    if _is_rule(text):
        return "<hr>"
    cls = ' class="text-center"' if centered else ""
    return f"<p{cls}>{html.escape(text)}</p>"


# --------------------------------------------------------------------------
# Rich text-layer extraction (Unicode PDFs)
# --------------------------------------------------------------------------

def _span_style(span: dict) -> tuple[bool, bool, bool]:
    font = (span.get("font") or "").lower()
    flags = span.get("flags", 0)
    bold = bool(flags & _FLAG_BOLD) or "bold" in font or "black" in font or "heavy" in font
    italic = bool(flags & _FLAG_ITALIC) or "italic" in font or "oblique" in font
    sup = bool(flags & _FLAG_SUPERSCRIPT)
    return bold, italic, sup


def _spans_html(spans: list[dict]) -> str:
    """Inline HTML for one visual line, preserving bold/italic/sup/color."""
    parts: list[str] = []
    prev_x1: float | None = None
    for s in spans:
        text = s.get("text", "")
        if not text:
            continue
        # PDFs sometimes drop the space between differently-styled spans.
        if (
            prev_x1 is not None
            and s["bbox"][0] - prev_x1 > 1.0
            and not text.startswith(" ")
            and parts
            and not parts[-1].endswith(" ")
        ):
            parts.append(" ")
        prev_x1 = s["bbox"][2]

        chunk = html.escape(text)
        bold, italic, sup = _span_style(s)
        color = s.get("color") or 0
        if color:  # non-black text keeps its color (e.g. links)
            chunk = f'<span style="color:#{color:06x}">{chunk}</span>'
        if italic:
            chunk = f"<i>{chunk}</i>"
        if bold:
            chunk = f"<b>{chunk}</b>"
        if sup:
            chunk = f"<sup>{chunk}</sup>"
        parts.append(chunk)
    return "".join(parts).strip()


def _is_pua(ch: str) -> bool:
    return 0xE000 <= ord(ch) <= 0xF8FF  # symbol-font bullets (Wingdings etc.)


def _bullet_rest(plain: str) -> str | None:
    """If the line starts with a bullet marker, return the text after it."""
    t = plain.lstrip()
    if not t:
        return None
    c = t[0]
    if c in _BULLET_LEADERS or _is_pua(c):
        return t[1:].lstrip()
    if c in _DASH_LEADERS and len(t) > 2 and t[1] == " ":
        return t[2:].lstrip()
    return None


def _strip_bullet_spans(spans: list[dict]) -> list[dict]:
    """Remove the leading bullet marker from a line's spans."""
    out = [dict(s) for s in spans]
    for s in out:
        t = s["text"].lstrip()
        if not t:
            s["text"] = ""
            continue
        c = t[0]
        if c in _BULLET_LEADERS or _is_pua(c):
            s["text"] = t[1:].lstrip()
        elif c in _DASH_LEADERS and len(t) > 2 and t[1] == " ":
            s["text"] = t[2:].lstrip()
        break  # only the first non-empty span carries the marker
    return [s for s in out if s["text"]]


def _body_size(spans: list[dict]) -> float:
    """Text-length-weighted median font size = the page's body size."""
    weighted: list[tuple[float, int]] = [
        (s["size"], len(s["text"].strip())) for s in spans if s["text"].strip()
    ]
    if not weighted:
        return 11.0
    weighted.sort()
    total = sum(w for _, w in weighted)
    acc = 0
    for size, w in weighted:
        acc += w
        if acc >= total / 2:
            return size
    return weighted[-1][0]


def _split_pair(spans: list[dict], col_l: float, col_r: float) -> tuple[list, list] | None:
    """Detect a left|right pair inside one line (name ....... link).

    PyMuPDF merges same-baseline text into one line, so a header row arrives as
    spans with one huge internal gap. Split at the largest gap when the right
    group hugs the right margin and the left group starts near the left.
    """
    if len(spans) < 2:
        return None
    w = col_r - col_l
    if w <= 0:
        return None
    best_i, best_gap = None, 0.0
    for i in range(len(spans) - 1):
        gap = spans[i + 1]["bbox"][0] - spans[i]["bbox"][2]
        if gap > best_gap:
            best_gap, best_i = gap, i
    if best_i is None or best_gap < 0.15 * w:
        return None
    left, right = spans[: best_i + 1], spans[best_i + 1 :]
    if col_r - right[-1]["bbox"][2] > 0.05 * w:
        return None
    if left[0]["bbox"][0] - col_l > 0.3 * w:
        return None
    return left, right


def _is_marker_only(plain: str) -> bool:
    """A line that is nothing but a list marker (PDFs box markers separately)."""
    t = plain.strip()
    return 0 < len(t) <= 2 and all(c in _BULLET_LEADERS or c in _DASH_LEADERS or _is_pua(c) for c in t)


def _extract_rich_page(page: fitz.Page) -> tuple[str, str]:
    """One Unicode page -> (semantic HTML, raw text for the legacy check)."""
    d = page.get_text("dict")

    lines: list[dict] = []
    raw_parts: list[str] = []
    for bi, b in enumerate(d.get("blocks", [])):
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            spans = [s for s in l.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            plain = "".join(s["text"] for s in spans)
            raw_parts.append(plain)
            lines.append({"block": bi, "bbox": list(l["bbox"]), "spans": spans, "plain": plain})
    if not lines:
        return "<p></p>", ""

    lines.sort(key=lambda L: (round(L["bbox"][1] / 3), L["bbox"][0]))

    # Normalize PDF-generator variance: fragments sharing a visual row (bullet
    # markers, left|right header pairs) arrive as separate lines/blocks — merge
    # them into one line so classification sees whole rows.
    merged_lines: list[dict] = []
    for L in lines:
        if merged_lines:
            P = merged_lines[-1]
            overlap = min(P["bbox"][3], L["bbox"][3]) - max(P["bbox"][1], L["bbox"][1])
            h = min(P["bbox"][3] - P["bbox"][1], L["bbox"][3] - L["bbox"][1])
            if h > 0 and overlap / h > 0.5 and L["bbox"][0] >= P["bbox"][2] - 1:
                if len(L["plain"].strip()) > len(P["plain"].strip()):
                    P["block"] = L["block"]  # a 1-char marker must not own the row
                P["spans"] = P["spans"] + L["spans"]
                P["plain"] = P["plain"] + " " + L["plain"]
                P["bbox"][1] = min(P["bbox"][1], L["bbox"][1])
                P["bbox"][2] = max(P["bbox"][2], L["bbox"][2])
                P["bbox"][3] = max(P["bbox"][3], L["bbox"][3])
                continue
        merged_lines.append(L)
    lines = merged_lines
    all_spans = [s for L in lines for s in L["spans"]]
    body = _body_size(all_spans)
    col_l = min(s["bbox"][0] for s in all_spans)
    col_r = max(s["bbox"][2] for s in all_spans)

    # List markers are often separate layout boxes ("•" alone) — attach each to
    # the text line sharing its row (max vertical overlap, to its right).
    markers = [L for L in lines if _is_marker_only(L["plain"])]
    texts = [L for L in lines if not _is_marker_only(L["plain"])]
    for M in markers:
        best, best_overlap = None, 0.0
        for T in texts:
            if T["bbox"][0] <= M["bbox"][0]:
                continue
            overlap = min(M["bbox"][3], T["bbox"][3]) - max(M["bbox"][1], T["bbox"][1])
            if overlap > best_overlap:
                best_overlap, best = overlap, T
        if best is not None and best_overlap > 0.5 * (M["bbox"][3] - M["bbox"][1]):
            best["li"] = True

    # Inline markers ("• text" in one line) mark the line and lose the glyph.
    for T in texts:
        if _bullet_rest(T["plain"]) is not None:
            T["li"] = True
            T["spans"] = _strip_bullet_spans(T["spans"])
    texts = [T for T in texts if T["spans"]]

    # elements: {kind: p|h1|h2|h3|li|hr|pair, inner, bbox, nlines, spans}
    elements: list[dict] = []
    para: dict | None = None
    last_li_block: int | None = None

    def flush_para():
        nonlocal para
        if para and " ".join(para["bits"]).strip():
            elements.append({
                "kind": "p", "inner": " ".join(para["bits"]).strip(),
                "y0": para["y0"], "y1": para["y1"], "x0": para["x0"], "x1": para["x1"],
                "nlines": para["n"], "spans": para["spans"],
            })
        para = None

    for T in texts:
        lb = T["bbox"]
        if _is_rule(T["plain"]):
            flush_para()
            elements.append({"kind": "hr", "inner": "", "y0": lb[1], "y1": lb[3], "x0": lb[0], "x1": lb[2]})
            last_li_block = None
            continue
        if T.get("li"):
            flush_para()
            elements.append({
                "kind": "li", "inner": _spans_html(T["spans"]),
                "y0": lb[1], "y1": lb[3], "x0": lb[0], "x1": lb[2],
            })
            last_li_block = T["block"]
            continue
        # wrapped continuation of a bullet = later line of the same source block
        if last_li_block is not None and T["block"] == last_li_block and elements and elements[-1]["kind"] == "li":
            elements[-1]["inner"] += " " + _spans_html(T["spans"])
            elements[-1]["y1"] = lb[3]
            continue
        last_li_block = None
        pair = _split_pair(T["spans"], col_l, col_r)
        if pair is not None:
            flush_para()
            left, right = pair
            left_html = _spans_html(left)
            # keep the left side's larger size (e.g. the person's name)
            left_size = max(s["size"] for s in left)
            if left_size >= 1.12 * body:
                left_html = f'<span style="font-size:{left_size:.0f}pt">{left_html}</span>'
            elements.append({
                "kind": "pair",
                "inner": f'<table class="pair"><tr><td>{left_html}</td><td class="r">{_spans_html(right)}</td></tr></table>',
                "y0": lb[1], "y1": lb[3], "x0": lb[0], "x1": lb[2],
            })
            continue
        if para and para["block"] != T["block"]:
            flush_para()
        if para is None:
            para = {"bits": [], "block": T["block"], "y0": lb[1], "y1": lb[3],
                    "x0": lb[0], "x1": lb[2], "n": 0, "spans": []}
        para["bits"].append(_spans_html(T["spans"]))
        para["spans"].extend(T["spans"])
        para["y0"] = min(para["y0"], lb[1])
        para["y1"] = max(para["y1"], lb[3])
        para["x0"] = min(para["x0"], lb[0])
        para["x1"] = max(para["x1"], lb[2])
        para["n"] += 1
    flush_para()

    # single-line paragraphs may be headings: size jump, or a short all-bold line
    for el in elements:
        if el["kind"] != "p" or el.get("nlines") != 1 or not el.get("spans"):
            continue
        max_size = max(s["size"] for s in el["spans"])
        all_bold = all(_span_style(s)[0] for s in el["spans"])
        plain_len = sum(len(s["text"]) for s in el["spans"])
        if max_size >= 1.3 * body:
            el["kind"] = "h1"
        elif max_size >= 1.12 * body:
            el["kind"] = "h2"
        elif all_bold and plain_len <= 80:
            el["kind"] = "h3"

    # same-row left|right pairs (e.g. name ....... LinkedIn) -> borderless 2-cell row
    elements.sort(key=lambda e: (e["y0"], e["x0"]))
    merged: list[dict] = []
    i = 0
    while i < len(elements):
        e1 = elements[i]
        if i + 1 < len(elements):
            e2 = elements[i + 1]
            overlap = min(e1["y1"], e2["y1"]) - max(e1["y0"], e2["y0"])
            h = max(min(e1["y1"] - e1["y0"], e2["y1"] - e2["y0"]), 1)
            if (
                e1["kind"] in ("p", "h1", "h2", "h3") and e2["kind"] in ("p", "h1", "h2", "h3")
                and overlap / h > 0.6
                and e1["x1"] < e2["x0"]
                and _right_aligned(e2["x0"], e2["x1"], col_l, col_r)
            ):
                left = f"<b>{e1['inner']}</b>" if e1["kind"] != "p" else e1["inner"]
                merged.append({
                    "kind": "pair",
                    "inner": f'<table class="pair"><tr><td>{left}</td><td class="r">{e2["inner"]}</td></tr></table>',
                    "y0": e1["y0"], "y1": max(e1["y1"], e2["y1"]), "x0": e1["x0"], "x1": e2["x1"],
                })
                i += 2
                continue
        merged.append(e1)
        i += 1

    # render, folding consecutive <li> into one <ul>
    out: list[str] = []
    li_buf: list[str] = []

    def flush_list():
        nonlocal li_buf
        if li_buf:
            out.append("<ul>\n" + "\n".join(f"<li>{x}</li>" for x in li_buf) + "\n</ul>")
            li_buf = []

    for el in merged:
        if el["kind"] == "li":
            li_buf.append(el["inner"])
            continue
        flush_list()
        if el["kind"] == "hr":
            out.append("<hr>")
        elif el["kind"] == "pair":
            out.append(el["inner"])
        elif el["kind"] in ("h1", "h2", "h3"):
            out.append(f"<{el['kind']}>{el['inner']}</{el['kind']}>")
        else:
            cls = ""
            if _centered(el["x0"], el["x1"], col_l, col_r):
                cls = ' class="text-center"'
            elif _right_aligned(el["x0"], el["x1"], col_l, col_r):
                cls = ' class="text-right"'
            out.append(f"<p{cls}>{el['inner']}</p>")
    flush_list()

    return "\n".join(out) or "<p></p>", " ".join(raw_parts)


def extract_pages(pdf_bytes: bytes) -> list[dict]:
    """Return [{page_number, html, method, needs_ocr}] from the text layer.

    Rich extraction keeps the styling the PDF already declares; pages whose
    text layer turns out to be legacy gibberish get flagged for OCR instead
    (their rich HTML is styled garbage either way and will be replaced).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages: list[dict] = []
        for i in range(doc.page_count):
            page_html, raw = _extract_rich_page(doc[i])
            pages.append({
                "page_number": i + 1,
                "html": page_html,
                "method": "text",
                "needs_ocr": 1 if looks_legacy(raw) else 0,
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
