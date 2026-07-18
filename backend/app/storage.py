"""Storage abstraction. Local filesystem for now; swap the class for S3/GCS later.

Callers deal only in opaque string *keys* (e.g. "documents/<id>/source.pdf"),
never filesystem paths, so a future backend swap touches nothing but this file.
"""
from pathlib import Path

from .config import settings


class LocalStorage:
    def __init__(self, base_dir: str):
        self.base = Path(base_dir).expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        p = (self.base / key).resolve()
        if self.base not in p.parents and p != self.base:
            raise ValueError(f"storage key escapes base dir: {key!r}")
        return p

    def save_bytes(self, key: str, data: bytes) -> str:
        p = self._resolve(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def read_bytes(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def delete_prefix(self, prefix: str) -> None:
        target = self._resolve(prefix)
        if target.is_dir():
            for child in sorted(target.rglob("*"), reverse=True):
                child.unlink() if child.is_file() else child.rmdir()
            target.rmdir()
        elif target.exists():
            target.unlink()


storage = LocalStorage(settings.storage_dir)
