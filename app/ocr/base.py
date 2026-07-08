from dataclasses import dataclass
from typing import Protocol


@dataclass
class OCRResult:
    text: str
    confidence: float  # aggregate 0-100, the engine's own certainty in its text recognition


class OCRProvider(Protocol):
    """Self-hosted OCR behind an interface (ADR-013), so a region-pinned
    managed OCR service can be substituted later without touching the
    ingestion pipeline. Synchronous by design -- OCR is a blocking, CPU/
    subprocess-bound operation; async callers wrap it (e.g. via
    `asyncio.to_thread`) rather than this interface pretending to be
    non-blocking itself.
    """

    engine_name: str
    engine_version: str

    def extract_text(self, image_bytes: bytes) -> OCRResult: ...
