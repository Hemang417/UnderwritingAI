from app.acquisition.document_parser import extract_fields

CLEAN_TEXT = (
    "MahaRERA Quarterly Progress Report Project: Lodha Park "
    "Total Units: 450 Possession Date: 31-12-2027"
)

# Actual Tesseract output on the degraded fixture scan (tests/fixtures/
# lodha_park_quarterly_report_scan.jpg) -- unit_count survives, the date
# gets garbled ("12" misread as "42" with a stray space).
GARBLED_TEXT = (
    "�MahaRERA Quarterly Progress Reoat Project: Lodha Park "
    "�Total Units: 450 oe Possession Date: 31- 42-2027"
)


def test_extracts_unit_count_from_clean_text():
    fields = extract_fields("quarterly_progress_report", CLEAN_TEXT)
    unit_count = next(f for f in fields if f.field_name == "unit_count")
    assert unit_count.raw_value == "450"
    assert unit_count.extraction_confidence == 90.0


def test_extracts_and_normalizes_possession_date_from_clean_text():
    fields = extract_fields("quarterly_progress_report", CLEAN_TEXT)
    possession_date = next(f for f in fields if f.field_name == "possession_date")
    assert possession_date.raw_value == "2027-12-31"


def test_unit_count_survives_realistic_ocr_noise():
    fields = extract_fields("quarterly_progress_report", GARBLED_TEXT)
    unit_count = next(f for f in fields if f.field_name == "unit_count")
    assert unit_count.raw_value == "450"


def test_garbled_date_is_rejected_rather_than_extracted_wrong():
    fields = extract_fields("quarterly_progress_report", GARBLED_TEXT)
    assert not any(f.field_name == "possession_date" for f in fields)


def test_unknown_doc_type_yields_no_fields():
    assert extract_fields("some_unrecognized_doc_type", CLEAN_TEXT) == []


def test_no_fields_when_nothing_matches():
    assert extract_fields("quarterly_progress_report", "irrelevant unrelated text") == []
