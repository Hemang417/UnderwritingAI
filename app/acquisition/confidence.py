def compute_composite_confidence(
    source_confidence: float,
    *,
    ocr_confidence: float | None = None,
    extraction_confidence: float | None = None,
) -> float:
    """One documented formula (SAD's "confidence-combination formula"),
    shared by every acquisition path so a clean structured fetch and an
    OCR'd document are scored the same way, not two ad hoc calculations.

    Multiplicative dampening: each imperfect stage (OCR recognition,
    field-extraction pattern match) can only reduce confidence below the
    source's own trust level, never raise it. A clean fetch with no
    OCR/extraction stage (both None) is unaffected -- composite equals
    source_confidence exactly.
    """
    composite = source_confidence
    if ocr_confidence is not None:
        composite *= ocr_confidence / 100
    if extraction_confidence is not None:
        composite *= extraction_confidence / 100
    return round(composite, 2)
