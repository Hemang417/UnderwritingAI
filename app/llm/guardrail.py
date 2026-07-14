import math
import re
from dataclasses import dataclass

"""Guardrail Validator (ADR-009 / PRD 13.1). Every number in generated
report text must trace back to the frozen Report JSON for that
ReportVersion -- this is the concrete, mechanical enforcement of "the LLM
never calculates or invents data," not a policy statement. Deterministic
extraction + normalization + tolerance matching; no LLM involved in
checking the LLM.

Per ADR-016, the reference set the guardrail matches against must include
every disclosed discrepancy block's *rejected* value, not just the
resolved one -- otherwise a correctly-disclosed losing figure (e.g. "460"
when RERA's 450 won) would look identical to an invented number and get
wrongly blocked. build_reference_set achieves this for free: it flattens
every numeric/date leaf in generated_json, and discrepancy blocks are
nested inside it like any other field (see app.reporting.assembly).
"""

_LAKH = 100_000
_CRORE = 10_000_000
REL_TOL = 1e-3
ABS_TOL = 0.5

_LAKH_CRORE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(lakh|crore)s?\b", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_DMY_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")
# Letter-led alphanumeric identifiers -- RERA registration numbers
# ("P51900001234", "PRM/KA/RERA/1251/2020") -- consumed whole so no digit
# run inside one is later picked up as a standalone numeric claim.
# Discovered against a real Groq response citing a project's RERA number in
# Project Overview: without this, "51900001234" (or "1900001234" once the
# leading digit was excluded by a narrower fix) was flagged as an
# unverifiable hallucination -- a false positive, not a real one. Numbers
# with a trailing unit attached ("450sqft") are unaffected: this pattern
# requires a *leading* letter, so a leading-digit token is left alone.
_ALPHANUMERIC_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9/-]*\d[A-Za-z0-9/-]*")
_PLAIN_NUMBER_RE = re.compile(r"₹?\s*-?\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class NumericClaim:
    raw_text: str
    kind: str  # "number" | "date"
    value: float | None = None
    normalized_date: str | None = None


@dataclass(frozen=True)
class ReferenceSet:
    numbers: list[tuple[str, float]]
    dates: list[tuple[str, str]]


@dataclass(frozen=True)
class GuardrailResult:
    passed: bool
    matched: list[dict]
    unmatched: list[dict]


def _spans_overlap(span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    return any(span[0] < s[1] and s[0] < span[1] for s in others)


def extract_numeric_claims(text: str) -> list[NumericClaim]:
    """Deterministic, locale-aware extraction (SAD S12): currency/lakh/
    crore/%/plain numbers, and ISO or DD-MM-YYYY dates. Each match consumes
    its span so e.g. "8.0%" is never double-counted as a bare "8.0" too.
    """
    claims: list[NumericClaim] = []
    consumed: list[tuple[int, int]] = []

    # Consumed but never turned into a claim: an identifier isn't a number.
    for m in _ALPHANUMERIC_ID_RE.finditer(text):
        consumed.append(m.span())

    for m in _LAKH_CRORE_RE.finditer(text):
        multiplier = _LAKH if m.group(2).lower() == "lakh" else _CRORE
        claims.append(NumericClaim(raw_text=m.group(0), kind="number", value=float(m.group(1)) * multiplier))
        consumed.append(m.span())

    for m in _PERCENT_RE.finditer(text):
        claims.append(NumericClaim(raw_text=m.group(0), kind="number", value=float(m.group(1))))
        consumed.append(m.span())

    for m in _DATE_ISO_RE.finditer(text):
        claims.append(
            NumericClaim(
                raw_text=m.group(0), kind="date", normalized_date=f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            )
        )
        consumed.append(m.span())

    for m in _DATE_DMY_RE.finditer(text):
        claims.append(
            NumericClaim(
                raw_text=m.group(0), kind="date", normalized_date=f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            )
        )
        consumed.append(m.span())

    for m in _PLAIN_NUMBER_RE.finditer(text):
        if _spans_overlap(m.span(), consumed):
            continue
        cleaned = m.group(0).replace("₹", "").replace(",", "").strip()
        if cleaned in ("", "-"):
            continue
        try:
            value = float(cleaned)
        except ValueError:
            continue
        claims.append(NumericClaim(raw_text=m.group(0), kind="number", value=value))

    return claims


def _flatten_leaves(obj, path: str = "") -> list[tuple[str, object]]:
    leaves: list[tuple[str, object]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            leaves.extend(_flatten_leaves(value, f"{path}/{key}"))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            leaves.extend(_flatten_leaves(value, f"{path}/{index}"))
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        leaves.append((path, obj))
    elif isinstance(obj, str) and _DATE_ISO_RE.fullmatch(obj):
        leaves.append((path, obj))
    return leaves


def build_reference_set(generated_json: dict) -> ReferenceSet:
    leaves = _flatten_leaves(generated_json)
    numbers = [(path, float(value)) for path, value in leaves if isinstance(value, (int, float))]
    dates = [(path, value) for path, value in leaves if isinstance(value, str)]
    return ReferenceSet(numbers=numbers, dates=dates)


def _numbers_close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)


def validate(text: str, reference_set: ReferenceSet) -> GuardrailResult:
    matched: list[dict] = []
    unmatched: list[dict] = []

    for claim in extract_numeric_claims(text):
        if claim.kind == "date":
            hit = next((path for path, value in reference_set.dates if value == claim.normalized_date), None)
        else:
            hit = next(
                (path for path, value in reference_set.numbers if _numbers_close(claim.value, value)), None
            )

        record = {"raw_text": claim.raw_text, "kind": claim.kind, "matched_path": hit}
        (matched if hit is not None else unmatched).append(record)

    return GuardrailResult(passed=not unmatched, matched=matched, unmatched=unmatched)
