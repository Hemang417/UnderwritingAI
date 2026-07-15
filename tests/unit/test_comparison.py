from dataclasses import dataclass, field

from app.reporting.comparison import compare_versions


@dataclass
class _FakeSection:
    section_name: str
    generated_text: str
    edited_text: str | None = None

    @property
    def effective_text(self) -> str:
        return self.edited_text if self.edited_text is not None else self.generated_text


@dataclass
class _FakeVersion:
    version_number: int
    generated_json: dict
    sections: list = field(default_factory=list)


def test_identical_versions_have_no_diffs():
    json_a = {"data_points": {"unit_count": {"value": 450.0}}}
    v1 = _FakeVersion(1, json_a, [_FakeSection("executive_summary", "Same text.")])
    v2 = _FakeVersion(2, json_a, [_FakeSection("executive_summary", "Same text.")])

    result = compare_versions(v1, v2)
    assert result.changed_values == []
    assert result.added_paths == []
    assert result.removed_paths == []
    assert all(not d.changed for d in result.section_diffs)


def test_changed_section_text_is_detected():
    json_a = {"a": 1}
    v1 = _FakeVersion(1, json_a, [_FakeSection("conclusion", "Old text.")])
    v2 = _FakeVersion(2, json_a, [_FakeSection("conclusion", "New text.")])

    result = compare_versions(v1, v2)
    diff = next(d for d in result.section_diffs if d.section_name == "conclusion")
    assert diff.changed
    assert diff.from_text == "Old text."
    assert diff.to_text == "New text."


def test_edited_text_is_what_gets_compared_not_the_original():
    json_a = {"a": 1}
    v1 = _FakeVersion(1, json_a, [_FakeSection("conclusion", "Original.", edited_text="Analyst edit.")])
    v2 = _FakeVersion(2, json_a, [_FakeSection("conclusion", "Original.")])

    result = compare_versions(v1, v2)
    diff = next(d for d in result.section_diffs if d.section_name == "conclusion")
    assert diff.changed
    assert diff.from_text == "Analyst edit."


def test_changed_numeric_value_is_detected_with_path():
    v1 = _FakeVersion(1, {"data_points": {"unit_count": {"value": 450.0}}}, [])
    v2 = _FakeVersion(2, {"data_points": {"unit_count": {"value": 500.0}}}, [])

    result = compare_versions(v1, v2)
    assert len(result.changed_values) == 1
    diff = result.changed_values[0]
    assert diff.path == "/data_points/unit_count/value"
    assert diff.from_value == 450.0
    assert diff.to_value == 500.0


def test_added_and_removed_paths_are_tracked_separately_from_changes():
    v1 = _FakeVersion(1, {"only_in_v1": 1, "shared": 1}, [])
    v2 = _FakeVersion(2, {"only_in_v2": 2, "shared": 1}, [])

    result = compare_versions(v1, v2)
    assert result.changed_values == []  # "shared" is unchanged
    assert result.added_paths == ["/only_in_v2"]
    assert result.removed_paths == ["/only_in_v1"]
