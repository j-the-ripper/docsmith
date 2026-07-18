"""DocSmith API — FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routers import documents, render

# Swagger UI lives under /api so Caddy's /api/* proxy reaches it too.
app = FastAPI(
    title="DocSmith API",
    version="0.2.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    # A restart mid-OCR would leave documents stuck in 'processing'; unblock
    # them (their un-OCR'd pages keep per-page / OCR-all retry paths).
    from sqlalchemy import update

    from .database import SessionLocal
    from .models import Document

    with SessionLocal() as db:
        db.execute(update(Document).where(Document.status == "processing").values(status="extracted"))
        db.commit()


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/api/fonts", tags=["meta"])
def list_fonts():
    from .config import AVAILABLE_FONTS

    return AVAILABLE_FONTS


# Everything the SPA calls lives under /api (Caddy proxies /api/* here).
app.include_router(documents.router, prefix="/api")
app.include_router(render.router, prefix="/api")
