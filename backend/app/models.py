"""ORM models for the document -> template -> fill pipeline."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class Document(Base):
    """An uploaded source PDF and the template derived from it."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    pdf_key: Mapped[str] = mapped_column(String(512))  # storage key, not a filesystem path
    page_count: Mapped[int] = mapped_column(Integer, default=0)

    # uploaded -> processing (background OCR) -> extracted -> template_ready
    status: Mapped[str] = mapped_column(String(32), default="uploaded")

    # Background-OCR progress (pages flagged for OCR / pages finished).
    ocr_total: Mapped[int] = mapped_column(Integer, default=0)
    ocr_done: Mapped[int] = mapped_column(Integer, default=0)

    # Render font (family name from config.AVAILABLE_FONTS).
    font: Mapped[str] = mapped_column(String(64), default="Noto Serif Gujarati")

    # The marked-up template: extracted HTML with {{ key }} placeholder tokens.
    template_html: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    pages: Mapped[list["ExtractedPage"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ExtractedPage.page_number",
    )
    placeholders: Mapped[list["Placeholder"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Placeholder.order",
    )
    fills: Mapped[list["Fill"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Fill.created_at",
    )


class ExtractedPage(Base):
    """One page's recovered text, as simple HTML paragraphs."""

    __tablename__ = "extracted_pages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_number: Mapped[int] = mapped_column(Integer)
    html: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(String(16), default="text")  # "text" | "ocr"
    needs_ocr: Mapped[int] = mapped_column(Integer, default=0)  # 1 = flagged legacy/scan, awaiting OCR

    document: Mapped["Document"] = relationship(back_populates="pages")


class Placeholder(Base):
    """A named variable the fill form will collect."""

    __tablename__ = "placeholders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(120))  # jinja identifier, e.g. seller_name
    label: Mapped[str] = mapped_column(String(255), default="")
    help_text: Mapped[str] = mapped_column(String(512), default="")
    default_value: Mapped[str] = mapped_column(Text, default="")
    order: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped["Document"] = relationship(back_populates="placeholders")


class Fill(Base):
    """A saved set of placeholder values (a draft of the finished document)."""

    __tablename__ = "fills"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), default="Draft")
    values_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="fills")
