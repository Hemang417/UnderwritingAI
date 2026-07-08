from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

settings = get_settings()


class ObjectStorage(Protocol):
    def save(self, key: str, content: bytes) -> str:
        """Persist content under key, return a storage reference."""
        ...

    def load(self, key: str) -> bytes:
        """Retrieve content previously saved under key."""
        ...


class LocalFilesystemStorage:
    """Stand-in for real cloud object storage (S3/Azure Blob), same
    reasoning as the fixture-backed adapters and self-hosted OCR: no cloud
    account exists yet, so store under a local directory behind this same
    interface. Swapping to a real object store later means a new class
    implementing `ObjectStorage`, not a change to any caller.
    """

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else Path(settings.document_storage_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        return self.base_dir / key

    def save(self, key: str, content: bytes) -> str:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    def load(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()
