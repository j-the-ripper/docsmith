"""Rebuild whitespace-aligned tables from OCR word boxes.

Typewriter-style documents (like Gujarati sale deeds) lay tables out with
aligned columns of whitespace, not ruled lines. Tesseract returns those cells
as a soup of words; this module re-detects the grid from word geometry:

  1. cluster words into visual lines (y proximity)
  2. find lines with large horizontal gaps (candidate column breaks)
  3. grow regions of vertically-adjacent lines whose gaps align
  4. derive column boundaries from whitespace shared by most tabular lines
  5. emit <table> rows, merging single-column lines into the previous row
     (multi-line cells, e.g. long owner-name lists)

Everything is geometry-relative (median word height), so it works at any DPI.
"""
import html
import statistics

COVERAGE = 0.7          # fraction of tabular lines that must share a whitespace band
MIN_GAP_FACTOR = 1.5    # gap >= factor * median word height -> column break
MIN_GAP_PX = 50.0       # absolute floor at 300dpi-ish scale
LINE_TOL = 0.55         # y-center tolerance (x median height) for same-line clustering
ROW_SPACING = 3.0       # max vertical gap between region lines (x median height);
                        # generous because OCR drops the dashed rule under headers


def _median_height(words):
    return statistics.median(w["y1"] - w["y0"] for w in words)


def _cluster_lines(words, med_h):
    """Group words into visual text lines by y-center proximity."""
    lines = []
    for w in sorted(words, key=lambda w: ((w["y0"] + w["y1"]) / 2, w["x0"])):
        cy = (w["y0"] + w["y1"]) / 2
        if lines and abs(cy - lines[-1]["cy"]) <= LINE_TOL * med_h:
            ln = lines[-1]
            ln["words"].append(w)
            ln["cy"] += (cy - ln["cy"]) / len(ln["words"])  # running mean
        else:
            lines.append({"cy": cy, "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x0"])
        ln["y0"] = min(w["y0"] for w in ln["words"])
        ln["y1"] = max(w["y1"] for w in ln["words"])
        ln["x0"] = ln["words"][0]["x0"]
        ln["x1"] = ln["words"][-1]["x1"]
    return lines


def _gaps(line_words, min_gap):
    out = []
    for a, b in zip(line_words, line_words[1:]):
        if b["x0"] - a["x1"] >= min_gap:
            out.append((a["x1"], b["x0"]))
    return out


def _share_gap(g1, g2, min_overlap):
    return any(min(a[1], b[1]) - max(a[0], b[0]) >= min_overlap for a in g1 for b in g2)


def _find_regions(lines, sigs, med_h, min_gap):
    """Runs of vertically-adjacent lines with aligned gaps (+ continuation lines)."""
    regions = []
    i = 0
    while i < len(lines):
        if not sigs[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(lines):
            nxt = j + 1
            if lines[nxt]["y0"] - lines[j]["y1"] > ROW_SPACING * med_h:
                break
            if sigs[nxt] and any(_share_gap(sigs[k], sigs[nxt], 0.4 * min_gap) for k in range(i, nxt)):
                j = nxt
                continue
            # continuation candidate: a narrow line (single wrapped cell)
            span_x0 = min(lines[k]["x0"] for k in range(i, j + 1))
            span_x1 = max(lines[k]["x1"] for k in range(i, j + 1))
            if (lines[nxt]["x1"] - lines[nxt]["x0"]) <= 0.55 * (span_x1 - span_x0):
                j = nxt
                continue
            break
        # NB: trailing continuation lines are legitimate — the last row's cell
        # can wrap for dozens of lines (owner-name lists), so no trailing trim.
        if j - i + 1 >= 3:
            regions.append((i, j))
            i = j + 1
        else:
            i += 1
    return regions


def _column_boundaries(tab_lines, min_gap):
    """x positions splitting columns: whitespace bands shared by >=COVERAGE of
    the tabular lines (leading/trailing space counts as whitespace)."""
    x0 = min(l["x0"] for l in tab_lines)
    x1 = max(l["x1"] for l in tab_lines)
    step = 4.0
    n_bins = max(1, int((x1 - x0) / step))
    votes = [0] * n_bins

    for l in tab_lines:
        spans = [(x0, l["x0"])] + _gaps(l["words"], 0.5 * min_gap) + [(l["x1"], x1)]
        for a, b in spans:
            lo = max(0, int((a - x0) / step))
            hi = min(n_bins, int((b - x0) / step))
            for k in range(lo, hi):
                votes[k] += 1

    need = max(1, int(COVERAGE * len(tab_lines)))
    bounds, k = [], 0
    while k < n_bins:
        if votes[k] >= need:
            s = k
            while k < n_bins and votes[k] >= need:
                k += 1
            width = (k - s) * step
            centre = x0 + (s + (k - s) / 2) * step
            if width >= 0.4 * min_gap and x0 + 8 * step < centre < x1 - 8 * step:
                bounds.append(centre)
        else:
            k += 1
    return bounds


def _build_rows(region_lines, region_sigs, boundaries):
    ncols = len(boundaries) + 1

    def col_of(w):
        c = (w["x0"] + w["x1"]) / 2
        for idx, b in enumerate(boundaries):
            if c < b:
                return idx
        return ncols - 1

    rows = []
    for l, sig in zip(region_lines, region_sigs):
        cells = [[] for _ in range(ncols)]
        for w in l["words"]:
            cells[col_of(w)].append(w["txt"])
        # Typewriter tables start every logical row with its serial/first column;
        # a line with an empty first column is a wrapped continuation of the row
        # above (long name lists, dates stacked under register numbers, ...).
        if rows and ncols >= 3 and not cells[0]:
            if not sig:
                # Contiguous text (no column gaps) = one wrapped cell. Assign the
                # whole line to its majority column so words that poke past the
                # column boundary don't spill into the neighbouring cell.
                counts = [len(c) for c in cells]
                target = counts.index(max(counts))
                rows[-1][target].extend(w["txt"] for w in l["words"])
            else:
                for idx, c in enumerate(cells):
                    rows[-1][idx].extend(c)
        else:
            rows.append(cells)
    return rows


def _table_html(rows):
    parts = ["<table>"]
    for r in rows:
        tds = "".join(f"<td>{html.escape(' '.join(c))}</td>" for c in r)
        parts.append(f"<tr>{tds}</tr>")
    parts.append("</table>")
    return "\n".join(parts)


def detect_tables(words):
    """words: [{id, txt, x0, y0, x1, y1}] -> [{y0, ids, html}] for each table."""
    if len(words) < 12:
        return []
    med_h = _median_height(words)
    min_gap = max(MIN_GAP_PX, MIN_GAP_FACTOR * med_h)
    lines = _cluster_lines(words, med_h)
    sigs = [_gaps(l["words"], min_gap) for l in lines]

    out = []
    for i, j in _find_regions(lines, sigs, med_h, min_gap):
        region = lines[i : j + 1]
        tab_lines = [l for k, l in enumerate(region) if sigs[i + k]]
        if len(tab_lines) < 2:
            continue
        bounds = _column_boundaries(tab_lines, min_gap)
        if not bounds:
            continue
        rows = _build_rows(region, sigs[i : j + 1], bounds)
        if len(rows) < 2 or (len(bounds) == 1 and len(rows) < 4):
            continue  # too small / too weak to be worth a grid
        out.append({
            "y0": min(l["y0"] for l in region),
            "ids": {w["id"] for l in region for w in l["words"]},
            "html": _table_html(rows),
        })
    return out
