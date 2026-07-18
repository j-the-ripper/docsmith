# DocSmith

Turn a PDF into a reusable **fill-in template**. Upload a document, mark the parts
that change as placeholders, then fill and export clean PDFs on demand — long
values **reflow** the surrounding text instead of overflowing a fixed box.

> Why rebuild instead of stamping the PDF? A PDF is a fixed layout and can't
> reflow, and many source PDFs are legacy-font-encoded (their text layer is
> gibberish). So DocSmith recovers the text (PyMuPDF text layer, or tesseract OCR
> for legacy/scanned pages), lets you mark placeholders, and re-renders the deed
> as HTML through **WeasyPrint** (Pango/HarfBuzz) — a live layout engine that
> shapes Gujarati correctly and reflows on every render.

## The flow

1. **Upload** a PDF → text is extracted per page. Pages whose text layer is
   legacy-font gibberish (or scans) are detected automatically and re-read with
   **OCR** (guj+eng) in the background, with live progress.
2. **Mark placeholders** — select any text, name it, insert. The original page
   image is shown side-by-side so you can proofread the recovered text (digits,
   dates, PAN codes). Commit → saves an HTML template + the placeholder list.
3. **Fill** the auto-generated form. Each value box is a small rich-text editor
   (bold / italic / underline / size / colour), so values carry their own formatting.
4. **Preview & export** — WeasyPrint renders a reflowed PDF you can preview inline
   and download.

## Stack

| Layer      | Choice                        | Notes                                            |
|------------|-------------------------------|--------------------------------------------------|
| Frontend   | React + Vite                  | Dependency-light rich-text via the Selection API |
| Backend    | FastAPI                       | Routes served under `/api`                       |
| DB         | SQLite (SQLAlchemy 2.0)       | Swap `DOCSMITH_DATABASE_URL` for Postgres later  |
| Storage    | Local filesystem              | Behind a `Storage` class → swap for S3/GCS later |
| PDF parse  | PyMuPDF + tesseract (OCR)     | `fonts-noto-core` + guj/eng data in the image    |
| PDF render | Jinja2 + WeasyPrint           | Noto Sans Gujarati resolved by name (fontconfig) |
| Web server | Caddy                         | Serves the SPA, reverse-proxies `/api` → backend |
| Runtime    | Docker Compose                | `backend` + `web` (Caddy+SPA)                    |

_No auth / user accounts yet — this is the core app, single-tenant._

## Run it (Docker)

```bash
docker compose up --build
# open http://localhost:8080
```

`web` (Caddy) serves the built SPA on port 8080 and proxies `/api` to `backend`.
SQLite DB + uploaded/generated files live in the `backend_data` volume.

## Local development (no Docker)

**Backend** (needs system libs for WeasyPrint + tesseract — `brew install pango tesseract tesseract-lang`):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (Vite dev server proxies `/api` → `localhost:8000`):

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

## API sketch

| Method | Path                                          | Purpose                          |
|--------|-----------------------------------------------|----------------------------------|
| POST   | `/api/documents`                              | Upload PDF, extract pages        |
| GET    | `/api/documents` · `/api/documents/{id}`      | List / detail                    |
| POST   | `/api/documents/{id}/pages/{n}/ocr`           | Re-extract a page with OCR       |
| PUT    | `/api/documents/{id}/template`                | Save template HTML + placeholders|
| POST   | `/api/documents/{id}/render[?download=1]`     | Render preview / export PDF      |
| GET/POST | `/api/documents/{id}/fills`                 | Save / list value drafts         |

Interactive docs at `http://localhost:8080/api/docs` (proxied) or
`http://localhost:8000/docs` in local dev.

## Table reconstruction

Typewriter-style tables (cheque lists, previous owners, boundaries) have no
ruled lines — the grid exists only as whitespace-aligned columns. OCR pages are
run through `table_detect.py`, which rebuilds `<table>` rows from the word
geometry: aligned column gaps → boundaries, and lines with an empty first
column merge into the row above (multi-line cells like long owner-name lists).

## Deliberate MVP corners

- **Scalar placeholders** (`{{ key }}`) only. Repeating groups (`{% for %}` — buyer
  lists, cheque rows) are modelled in the data layer but not yet in the editor.
- OCR output needs a human eye (digits, PAN codes, English tokens).
- Table detection is heuristic — headers can split across rows and stray words
  can land in the wrong cell; the editor's side-by-side view is for fixing that.
- Output is *clean & close*, re-typeset in Unicode — not byte-identical to the source.
- Local storage + SQLite are intentionally swappable seams, not production choices.
