from dataclasses import dataclass

from app.reporting.models import ReportVersion

"""Version comparison (M8 "done when": regeneration produces a new,
comparable version). Deliberately a separate, more general flatten than
app.llm.guardrail's -- the guardrail only cares about numeric/date claims
for hallucination-checking, but a human comparing two report versions
wants to see *every* changed fact (e.g. a DataPoint's source flipping from
MahaRERA to Developer Website), not just numbers.
"""


@dataclass(frozen=True)
class SectionDiff:
    section_name: str
    changed: bool
    from_text: str | None
    to_text: str | None


@dataclass(frozen=True)
class ValueDiff:
    path: str
    from_value: object
    to_value: object


@dataclass(frozen=True)
class VersionComparison:
    from_version_number: int
    to_version_number: int
    section_diffs: list[SectionDiff]
    changed_values: list[ValueDiff]
    added_paths: list[str]
    removed_paths: list[str]


def _flatten_all_leaves(obj, path: str = "") -> dict[str, object]:
    leaves: dict[str, object] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            leaves.update(_flatten_all_leaves(value, f"{path}/{key}"))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            leaves.update(_flatten_all_leaves(value, f"{path}/{index}"))
    else:
        leaves[path] = obj
    return leaves


def compare_versions(from_version: ReportVersion, to_version: ReportVersion) -> VersionComparison:
    from_sections = {s.section_name: s.effective_text for s in from_version.sections}
    to_sections = {s.section_name: s.effective_text for s in to_version.sections}

    section_diffs = [
        SectionDiff(
            section_name=name,
            changed=from_sections.get(name) != to_sections.get(name),
            from_text=from_sections.get(name),
            to_text=to_sections.get(name),
        )
        for name in sorted(set(from_sections) | set(to_sections))
    ]

    from_leaves = _flatten_all_leaves(from_version.generated_json or {})
    to_leaves = _flatten_all_leaves(to_version.generated_json or {})

    changed_values = [
        ValueDiff(path=path, from_value=from_leaves[path], to_value=to_leaves[path])
        for path in sorted(set(from_leaves) & set(to_leaves))
        if from_leaves[path] != to_leaves[path]
    ]
    added_paths = sorted(set(to_leaves) - set(from_leaves))
    removed_paths = sorted(set(from_leaves) - set(to_leaves))

    return VersionComparison(
        from_version_number=from_version.version_number,
        to_version_number=to_version.version_number,
        section_diffs=section_diffs,
        changed_values=changed_values,
        added_paths=added_paths,
        removed_paths=removed_paths,
    )
