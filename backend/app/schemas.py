"""Pydantic request/response models (the API contract with the React app)."""
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class PageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    page_number: int
    html: str
    method: str
    needs_ocr: int = 0


class PlaceholderIn(BaseModel):
    key: str
    label: str = ""
    help_text: str = ""
    default_value: str = ""
    order: int = 0

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        v = v.strip()
        if not KEY_RE.match(v):
            raise ValueError("key must be a valid identifier (letters, digits, underscore; not starting with a digit)")
        return v


class PlaceholderOut(PlaceholderIn):
    model_config = ConfigDict(from_attributes=True)
    id: str


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    original_filename: str
    page_count: int
    status: str
    ocr_total: int = 0
    ocr_done: int = 0
    font: str = "Noto Serif Gujarati"
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    template_html: str
    pages: list[PageOut] = []
    placeholders: list[PlaceholderOut] = []


class TemplateSaveIn(BaseModel):
    template_html: str
    placeholders: list[PlaceholderIn]


class FontIn(BaseModel):
    font: str


class RenderIn(BaseModel):
    # placeholder key -> value (may contain sanitized inline HTML like <b>, <i>, styled <span>)
    values: dict[str, str] = Field(default_factory=dict)


class FillIn(BaseModel):
    name: str = "Draft"
    values: dict[str, str] = Field(default_factory=dict)


class FillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    values: dict[str, str]
    created_at: datetime
