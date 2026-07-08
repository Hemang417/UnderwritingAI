from app.acquisition.confidence import compute_composite_confidence


def test_clean_fetch_with_no_ocr_or_extraction_stage_is_unaffected():
    assert compute_composite_confidence(95.0) == 95.0


def test_ocr_and_extraction_dampen_confidence_below_source_alone():
    composite = compute_composite_confidence(95.0, ocr_confidence=90.0, extraction_confidence=85.0)
    assert composite < 95.0
    assert composite == round(95.0 * 0.90 * 0.85, 2)


def test_perfect_ocr_and_extraction_leaves_composite_equal_to_source():
    assert compute_composite_confidence(95.0, ocr_confidence=100.0, extraction_confidence=100.0) == 95.0


def test_only_ocr_confidence_applies_when_extraction_missing():
    composite = compute_composite_confidence(95.0, ocr_confidence=80.0)
    assert composite == round(95.0 * 0.80, 2)
