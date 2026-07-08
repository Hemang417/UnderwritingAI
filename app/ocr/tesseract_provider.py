import io

import pytesseract
from PIL import Image

from app.core.config import get_settings
from app.ocr.base import OCRResult

settings = get_settings()

if settings.tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd


class TesseractOCRProvider:
    """MVP default per ADR-013: self-hosted, no scanned filings sent to a
    third-party OCR vendor. Accuracy against real scans is the M3
    validation checkpoint the ADR calls for.
    """

    engine_name = "tesseract"

    @property
    def engine_version(self) -> str:
        return str(pytesseract.get_tesseract_version())

    def extract_text(self, image_bytes: bytes) -> OCRResult:
        image = Image.open(io.BytesIO(image_bytes))
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

        words = []
        confidences = []
        for word, conf in zip(data["text"], data["conf"], strict=True):
            if not word.strip():
                continue
            words.append(word)
            conf_value = float(conf)
            if conf_value >= 0:  # tesseract uses -1 for non-word regions
                confidences.append(conf_value)

        text = " ".join(words)
        avg_confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
        return OCRResult(text=text, confidence=avg_confidence)
