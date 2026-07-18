"""Preview/export the filled document, and save/load fills (value drafts)."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document, Fill
from ..schemas import FillIn, FillOut, RenderIn
from ..services import pdf_render

router = APIRouter(prefix="/documents", tags=["render"])


def _get_doc(document_id: str, db: Session) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return doc


@router.post("/{document_id}/render")
def render_document(
    document_id: str,
    payload: RenderIn,
    download: bool = Query(False, description="attach as a download instead of inline preview"),
    db: Session = Depends(get_db),
):
    doc = _get_doc(document_id, db)
    if not doc.template_html:
        raise HTTPException(status_code=409, detail="no template saved yet")
    try:
        pdf = pdf_render.render_pdf(doc.template_html, payload.values, font=doc.font)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"render failed: {exc}") from exc

    disposition = "attachment" if download else "inline"
    filename = f"{doc.name or 'document'}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.get("/{document_id}/fills", response_model=list[FillOut])
def list_fills(document_id: str, db: Session = Depends(get_db)):
    _get_doc(document_id, db)
    rows = db.scalars(
        select(Fill).where(Fill.document_id == document_id).order_by(Fill.created_at.desc())
    ).all()
    return [FillOut(id=r.id, name=r.name, values=json.loads(r.values_json or "{}"), created_at=r.created_at) for r in rows]


@router.post("/{document_id}/fills", response_model=FillOut, status_code=201)
def save_fill(document_id: str, payload: FillIn, db: Session = Depends(get_db)):
    _get_doc(document_id, db)
    fill = Fill(document_id=document_id, name=payload.name, values_json=json.dumps(payload.values, ensure_ascii=False))
    db.add(fill)
    db.commit()
    db.refresh(fill)
    return FillOut(id=fill.id, name=fill.name, values=payload.values, created_at=fill.created_at)
