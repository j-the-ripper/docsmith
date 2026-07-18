"""Document lifecycle: upload -> extract -> (auto/manual OCR) -> save template.

Legacy-font pages (gibberish text layer) are detected at upload and OCR'd in a
background task; the document sits in status "processing" with ocr_done/ocr_total
progress until every flagged page is re-read.
"""
import html as html_mod
import logging
import re
import time

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import FONT_NAMES, settings
from ..database import SessionLocal, get_db
from ..models import Document, ExtractedPage, Placeholder
from ..schemas import DocumentDetail, DocumentSummary, FontIn, TemplateSaveIn
from ..services import pdf_extract
from ..storage import storage

logger = logging.getLogger("docsmith.ocr")

router = APIRouter(prefix="/documents", tags=["documents"])


def _get_doc(document_id: str, db: Session) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return doc


def _html_to_text(fragment: str) -> str:
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))


def run_document_ocr(document_id: str) -> None:
    """Background task: OCR every page flagged needs_ocr, then unblock the doc.

    Runs in Starlette's threadpool with its own DB session. Per-page failures
    are logged and skipped so one bad page can't wedge the whole document.
    """
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None or not doc.pdf_key or not storage.exists(doc.pdf_key):
            return
        pdf = storage.read_bytes(doc.pdf_key)
        for page in [p for p in doc.pages if p.needs_ocr]:
            t0 = time.monotonic()
            try:
                page.html = pdf_extract.ocr_page_html(pdf, page.page_number, langs=settings.ocr_langs)
                page.method = "ocr"
                logger.info("OCR doc=%s page=%s took %.1fs", document_id, page.page_number, time.monotonic() - t0)
            except Exception:
                logger.exception("OCR failed doc=%s page=%s", document_id, page.page_number)
            page.needs_ocr = 0
            doc.ocr_done = (doc.ocr_done or 0) + 1
            db.commit()
        doc.status = "extracted"
        db.commit()
    except Exception:
        logger.exception("OCR task aborted doc=%s", document_id)
    finally:
        db.close()


@router.get("", response_model=list[DocumentSummary])
def list_documents(db: Session = Depends(get_db)):
    return db.scalars(select(Document).order_by(Document.created_at.desc())).all()


@router.post("", response_model=DocumentDetail, status_code=201)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if (file.content_type or "") not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=415, detail="please upload a PDF")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"file exceeds {settings.max_upload_mb} MB")

    try:
        pages = pdf_extract.extract_pages(data)
    except Exception as exc:  # malformed PDF, etc.
        raise HTTPException(status_code=422, detail=f"could not read PDF: {exc}") from exc

    flagged = sum(p["needs_ocr"] for p in pages)
    doc = Document(
        name=(file.filename or "document").rsplit(".", 1)[0][:255] or "document",
        original_filename=file.filename or "document.pdf",
        pdf_key="",
        page_count=len(pages),
        status="processing" if flagged else "extracted",
        ocr_total=flagged,
        ocr_done=0,
    )
    db.add(doc)
    db.flush()  # assigns doc.id

    doc.pdf_key = storage.save_bytes(f"documents/{doc.id}/source.pdf", data)
    for p in pages:
        db.add(ExtractedPage(document_id=doc.id, **p))

    db.commit()
    db.refresh(doc)
    if flagged:
        background_tasks.add_task(run_document_ocr, doc.id)
    return doc


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: str, db: Session = Depends(get_db)):
    return _get_doc(document_id, db)


@router.get("/{document_id}/pdf")
def get_source_pdf(document_id: str, db: Session = Depends(get_db)):
    doc = _get_doc(document_id, db)
    if not doc.pdf_key or not storage.exists(doc.pdf_key):
        raise HTTPException(status_code=404, detail="source PDF missing")
    return Response(content=storage.read_bytes(doc.pdf_key), media_type="application/pdf")


@router.get("/{document_id}/pages/{page_number}/image")
def page_image(document_id: str, page_number: int, db: Session = Depends(get_db)):
    """Original-page render (PNG) for the side-by-side editor view. Cached."""
    doc = _get_doc(document_id, db)
    key = f"documents/{doc.id}/pages/p{page_number}.png"
    if not storage.exists(key):
        if not doc.pdf_key or not storage.exists(doc.pdf_key):
            raise HTTPException(status_code=404, detail="source PDF missing")
        try:
            png = pdf_extract.render_page_png(storage.read_bytes(doc.pdf_key), page_number)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        storage.save_bytes(key, png)
    return Response(
        content=storage.read_bytes(key),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/{document_id}/ocr", response_model=DocumentDetail)
def ocr_all_pages(document_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Re-scan the document: flag every page whose current text still looks
    like legacy gibberish (or has no text) and OCR them in the background."""
    doc = _get_doc(document_id, db)
    if doc.status == "processing":
        raise HTTPException(status_code=409, detail="OCR already running for this document")
    if not doc.pdf_key or not storage.exists(doc.pdf_key):
        raise HTTPException(status_code=404, detail="source PDF missing")

    flagged = 0
    for p in doc.pages:
        if pdf_extract.looks_legacy(_html_to_text(p.html)):
            p.needs_ocr = 1
            flagged += 1
        else:
            p.needs_ocr = 0
    if flagged:
        doc.ocr_total = flagged
        doc.ocr_done = 0
        doc.status = "processing"
        # Any saved template was built from the gibberish text — reset it so the
        # editor reopens in page mode on the recovered Unicode text.
        doc.template_html = ""
        doc.placeholders.clear()
    db.commit()
    db.refresh(doc)
    if flagged:
        background_tasks.add_task(run_document_ocr, doc.id)
    return doc


@router.post("/{document_id}/pages/{page_number}/ocr", response_model=DocumentDetail)
def ocr_page(document_id: str, page_number: int, db: Session = Depends(get_db)):
    """Re-extract a single page with OCR, synchronously."""
    doc = _get_doc(document_id, db)
    if not doc.pdf_key or not storage.exists(doc.pdf_key):
        raise HTTPException(status_code=404, detail="source PDF missing")
    try:
        html = pdf_extract.ocr_page_html(storage.read_bytes(doc.pdf_key), page_number, langs=settings.ocr_langs)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"OCR failed: {exc}") from exc

    page = db.scalar(
        select(ExtractedPage).where(
            ExtractedPage.document_id == document_id,
            ExtractedPage.page_number == page_number,
        )
    )
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    page.html = html
    page.method = "ocr"
    page.needs_ocr = 0
    db.commit()
    db.refresh(doc)
    return doc


@router.put("/{document_id}/font", response_model=DocumentDetail)
def set_font(document_id: str, payload: FontIn, db: Session = Depends(get_db)):
    """Choose which installed font the document renders/exports with."""
    doc = _get_doc(document_id, db)
    if payload.font not in FONT_NAMES:
        raise HTTPException(status_code=400, detail=f"unknown font: {payload.font!r}")
    doc.font = payload.font
    db.commit()
    db.refresh(doc)
    return doc


@router.put("/{document_id}/template", response_model=DocumentDetail)
def save_template(document_id: str, payload: TemplateSaveIn, db: Session = Depends(get_db)):
    """Commit the marked-up template HTML and its placeholder definitions."""
    doc = _get_doc(document_id, db)

    keys = [p.key for p in payload.placeholders]
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=400, detail="duplicate placeholder keys")

    doc.template_html = payload.template_html
    doc.status = "template_ready"

    doc.placeholders.clear()  # cascade delete-orphan replaces the whole set
    db.flush()
    for i, p in enumerate(payload.placeholders):
        db.add(Placeholder(document_id=doc.id, order=p.order or i, **p.model_dump(exclude={"order"})))

    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = _get_doc(document_id, db)
    storage.delete_prefix(f"documents/{doc.id}")
    db.delete(doc)
    db.commit()
    return Response(status_code=204)
