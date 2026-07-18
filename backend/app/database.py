"""SQLAlchemy engine/session wiring. SQLite now, Postgres-ready."""
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

# For a file-backed SQLite URL, make sure the parent directory exists before connecting.
if _is_sqlite and ":///" in settings.database_url:
    db_path = settings.database_url.split(":///", 1)[1]
    if db_path and db_path != ":memory:":
        Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_columns() -> None:
    """Tiny forward-only migration: add columns introduced after first release.

    create_all() never alters existing tables, so an existing volume DB needs
    these ALTERs. Works on both SQLite and Postgres.
    """
    from sqlalchemy import inspect, text as sql

    wanted = {
        "documents": {
            "ocr_total": "INTEGER NOT NULL DEFAULT 0",
            "ocr_done": "INTEGER NOT NULL DEFAULT 0",
            "font": "VARCHAR(64) NOT NULL DEFAULT 'Noto Serif Gujarati'",
        },
        "extracted_pages": {"needs_ocr": "INTEGER NOT NULL DEFAULT 0"},
    }
    insp = inspect(engine)
    for table, cols in wanted.items():
        if not insp.has_table(table):
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        missing = {name: ddl for name, ddl in cols.items() if name not in have}
        if not missing:
            continue
        with engine.begin() as conn:
            for name, ddl in missing.items():
                conn.execute(sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db() -> None:
    from . import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)
    _ensure_columns()
