"""Fill a template with values and render a reflowable PDF.

Pipeline:  template_html + values  ->  Jinja2  ->  full HTML doc  ->  WeasyPrint  ->  PDF

WeasyPrint runs a live layout engine (Pango/HarfBuzz), so a long value *reflows*
the following text onto new lines instead of overflowing a fixed box. That live
relayout is the entire reason we rebuild the deed as HTML rather than stamping
text onto the original fixed-layout PDF.

User-supplied values may carry inline formatting (bold/italic/size/colour) from
the rich-text boxes in the form, so each value is HTML-sanitised (allow-list)
before it reaches the template.
"""
from pathlib import Path

import bleach
from bleach.css_sanitizer import CSSSanitizer
from jinja2 import Environment, Undefined
from markupsafe import Markup
from weasyprint import HTML

_ASSETS = Path(__file__).resolve().parent.parent / "render_assets"
_CSS = (_ASSETS / "document.css").read_text(encoding="utf-8")

# Inline formatting we accept from the value editors — nothing block-level, no links/scripts.
_ALLOWED_TAGS = ["b", "strong", "i", "em", "u", "s", "span", "br", "sub", "sup", "small", "mark"]
_ALLOWED_ATTRS = {"span": ["style"], "mark": ["style"]}
_CSS_SANITIZER = CSSSanitizer(
    allowed_css_properties=[
        "font-weight", "font-style", "font-size", "text-decoration",
        "color", "background-color", "font-family",
    ]
)


class _Empty(Undefined):
    """Unfilled placeholders render as empty string instead of raising/printing noise."""

    def __str__(self) -> str:  # noqa: D401
        return ""

    __html__ = __str__


_env = Environment(autoescape=False, undefined=_Empty)


def sanitize_value(raw: str) -> str:
    return bleach.clean(
        raw or "",
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        css_sanitizer=_CSS_SANITIZER,
        strip=True,
    )


def render_html(template_html: str, values: dict[str, str], font: str | None = None) -> str:
    """Fill the template and wrap it in a complete, styled HTML document.

    `font` (a family from config.AVAILABLE_FONTS) overrides the stylesheet's
    default document face; unknown names are ignored, so no CSS injection.
    """
    from ..config import DEFAULT_FONT, FONT_NAMES

    safe = {k: Markup(sanitize_value(v)) for k, v in (values or {}).items()}
    body = _env.from_string(template_html or "").render(**safe)
    font_css = ""
    if font and font in FONT_NAMES and font != DEFAULT_FONT:
        font_css = (
            f"<style>html {{ font-family: '{font}', 'Noto Serif Gujarati', "
            "'Noto Sans Gujarati', 'Noto Sans', sans-serif; }}</style>"
        )
    return (
        "<!doctype html><html lang=\"gu\"><head><meta charset=\"utf-8\">"
        f"<style>{_CSS}</style>{font_css}</head><body>{body}</body></html>"
    )


def render_pdf(template_html: str, values: dict[str, str], font: str | None = None) -> bytes:
    full = render_html(template_html, values, font=font)
    return HTML(string=full, base_url=str(_ASSETS)).write_pdf()
