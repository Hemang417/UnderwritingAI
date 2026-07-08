import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class ExtractedField:
    field_name: str
    raw_value: str
    extraction_confidence: float


@dataclass
class FieldPattern:
    field_name: str
    pattern: re.Pattern
    confidence: float
    normalize: Callable[[str], str] | None = None


def _ddmmyyyy_to_iso(value: str) -> str:
    day, month, year = re.split(r"-", value)
    return f"{year}-{int(month):02d}-{int(day):02d}"


# Patterns are deliberately strict (no internal whitespace inside the
# captured token) rather than lenient: a real scanned document's OCR text
# has noise, and a loose pattern can confidently "extract" a misread value
# (e.g. OCR turning "12" into "42") that's wrong, not just imprecise.
# Rejecting the match entirely when the token doesn't cleanly parse is
# safer than accepting a plausible-looking wrong number.
QUARTERLY_PROGRESS_REPORT_PATTERNS: list[FieldPattern] = [
    FieldPattern(
        field_name="unit_count",
        pattern=re.compile(r"Total\s+Units\s*[:\-]?\s*(\d+)", re.IGNORECASE),
        confidence=90.0,
    ),
    FieldPattern(
        field_name="possession_date",
        pattern=re.compile(r"Possession\s+Date\s*[:\-]?\s*(\d{1,2}-\d{1,2}-\d{4})", re.IGNORECASE),
        confidence=90.0,
        normalize=_ddmmyyyy_to_iso,
    ),
]

DOC_TYPE_PATTERNS: dict[str, list[FieldPattern]] = {
    "quarterly_progress_report": QUARTERLY_PROGRESS_REPORT_PATTERNS,
}


def extract_fields(doc_type: str, text: str) -> list[ExtractedField]:
    """Doc-type-and-state-specific parser (SAD's OCR pipeline design):
    layouts vary by state and change over time, so this is a pluggable
    strategy keyed by doc_type, not one universal parser. Fields whose
    pattern doesn't match are simply omitted -- a document doesn't have to
    yield every field, and a non-match is far safer than a guess.
    """
    patterns = DOC_TYPE_PATTERNS.get(doc_type, [])
    extracted = []
    for field_pattern in patterns:
        match = field_pattern.pattern.search(text)
        if not match:
            continue
        raw_value = match.group(1)
        if field_pattern.normalize:
            raw_value = field_pattern.normalize(raw_value)
        extracted.append(
            ExtractedField(
                field_name=field_pattern.field_name,
                raw_value=raw_value,
                extraction_confidence=field_pattern.confidence,
            )
        )
    return extracted
