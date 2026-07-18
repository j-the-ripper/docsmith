"""Runtime configuration, sourced from DOCSMITH_* environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCSMITH_", env_file=".env", extra="ignore")

    # SQLite today. Point this at a postgresql+psycopg:// DSN later — nothing else changes.
    database_url: str = "sqlite:///./data/docsmith.db"

    # Local filesystem storage today; swap the Storage implementation later for S3/GCS.
    storage_dir: str = "./data/storage"

    # Comma-separated list of allowed browser origins for the dev server / Caddy host.
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    max_upload_mb: int = 40
    ocr_langs: str = "guj+eng"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

# Fonts available for rendered documents. Every name must resolve via fontconfig
# inside the backend image (fonts-noto-core or /usr/share/fonts/truetype/docsmith).
AVAILABLE_FONTS = [
    {"name": "Noto Serif Gujarati", "label": "Noto Serif Gujarati — traditional print (default)"},
    {"name": "Noto Sans Gujarati", "label": "Noto Sans Gujarati — modern sans"},
    {"name": "Rasa", "label": "Rasa — classic book-print serif"},
]
FONT_NAMES = {f["name"] for f in AVAILABLE_FONTS}
DEFAULT_FONT = "Noto Serif Gujarati"  # must match document.css's base font-family
