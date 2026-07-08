# Architecture Decision Records

## Investment Committee Intelligence Platform

Each record follows: Title / Status / Context / Decision / Consequences. All are **Accepted** as of this document's approval; none are provisional unless noted.

---

### ADR-001: Modular Monolith over Microservices for MVP

**Status:** Accepted

**Context:** The platform is sized for mid-scale (multiple offices, dozens of analysts, hundreds of tracked projects) — not yet at a scale where independent service deployment/scaling pays for its operational cost. However, the domain has clearly separable concerns (discovery, acquisition, analytics, reporting) that must not become entangled.

**Decision:** Build a single deployable (FastAPI app + Celery workers sharing one codebase) internally partitioned into bounded contexts, each with an owned schema and a narrow published interface (Python Protocols/Pydantic schemas), enforced structurally (no context imports another's ORM models directly — only its repository/service interface).

**Consequences:** Faster to build and operate than microservices at this scale; a single deployment pipeline and transaction boundary simplify consistency (e.g., writing a DataPoint and its audit entry in one transaction). The risk — contexts silently coupling over time — is mitigated by enforcing the interface boundary in code review and, if needed, an import-linter rule. Splitting a context into a standalone service later is a scoped extraction, not a rewrite, provided this discipline holds.

---

### ADR-002: PostgreSQL as the Sole System of Record

**Status:** Accepted

**Context:** The platform needs strong transactional guarantees for auditability (versioning, conflict logs, publish immutability) alongside schema flexibility for heterogeneous adapter data.

**Decision:** PostgreSQL (primary + read replica) is the only database. JSONB columns absorb schema variability where needed; no separate document store or polyglot persistence for MVP.

**Consequences:** ACID transactions and foreign keys give real guarantees for audit-critical writes (e.g., a DataPoint and its ConflictResolutionLog land together or not at all). The read replica offloads Analytics/reporting reads from the primary. Risk: JSONB-heavy tables can be harder to query/index than fully relational ones — mitigated by ADR-003's snapshot table for the highest-traffic read path.

---

### ADR-003: Generic `data_points` (EAV) Fact Table + Derived Snapshot for Reads

**Status:** Accepted

**Context:** Per-datapoint provenance (source, timestamp, confidence, version) must apply uniformly to every field, across state adapters whose field sets are genuinely heterogeneous (MahaRERA's fields don't match what a future Karnataka adapter will return). A per-field-column approach (`unit_count`, `unit_count_source`, `unit_count_confidence`, ...) would require a migration for every new field or adapter.

**Decision:** Use a single generic `data_points` fact table (entity_type, entity_id, field_name, value, source, confidence, version, status, effective_date, ...), with a maintained denormalized "current snapshot" table/materialized view per entity type as the fast read path for Analytics and Report Assembly.

**Consequences:** New fields and new state adapters are additive — no schema migration required, and one uniform mechanism handles versioning/conflict-resolution/audit for every field, present and future. Trade-off: EAV is inherently harder to query/aggregate in raw SQL and weaker on DB-level type enforcement than native columns — mitigated by application-layer validation against a `field_catalog` (field_name → type, unit, valid range, criticality tier, staleness threshold) and by keeping the snapshot table as the primary read path so most consumers never query the EAV table directly.

---

### ADR-004: Adapter Pattern — Common 6-Method Interface, No Business Logic in Adapters

**Status:** Accepted

**Context:** External sources (RERA per-state, developer sites, market data, infrastructure, news, government data, future paid sources) vary wildly in structure and maturity. The PRD requires that adding a source never requires modifying business logic.

**Decision:** Every source implements the same interface — `search_project()`, `get_project()`, `get_documents()`, `get_progress()`, `get_inventory()`, `get_quarterly_reports()` — plus declared capability flags (not every source meaningfully supports all six methods). Adapters retrieve and return structured data only; sequencing, retries, prioritization, and conflict resolution live entirely in the orchestrator/normalization layer.

**Consequences:** Adding a state or source is a new adapter class + a config row — zero orchestrator changes (Open/Closed principle in practice, not just in principle). Capability flags let the orchestrator skip inapplicable calls rather than adapters faking empty responses. Risk: interface design could overfit to the first (MahaRERA) implementation — mitigated by building a second, minimal stub adapter early specifically to validate the contract generalizes (see roadmap M10).

---

### ADR-005: Orchestrator-Level Retry, Circuit Breaker, and Rate Limiting (Redis-Backed)

**Status:** Accepted

**Context:** Government and developer sites fail, rate-limit, or CAPTCHA-block unpredictably. Handling this ad hoc per-adapter would produce inconsistent resilience behavior and no central visibility into source health.

**Decision:** Resilience policy is centralized in the orchestrator: exponential backoff + jitter with bounded retries (distinguishing retryable errors — timeout/5xx/429 — from non-retryable ones — 404/CAPTCHA/auth failure); a per-source circuit breaker (Redis-backed so state is shared across worker processes) that opens after repeated failures, cools down, and half-open-probes; and a Redis token-bucket rate limiter plus response caching per source.

**Consequences:** Consistent, observable resilience behavior across every source, and one place to alert on source degradation. Adds a Redis dependency for shared state beyond its role as the Celery broker — acceptable since Redis is already present for that purpose (ADR-011).

---

### ADR-006: Deterministic, Configurable, Per-Field-Type Conflict Resolution

**Status:** Accepted

**Context:** Sources will disagree (e.g., unit count from a RERA filing vs. a developer website). Silently averaging or preferring the "latest" value would violate the explainability and auditability principles.

**Decision:** Each field type has a configured source-priority order (not hardcoded); when two current values disagree, the priority rule picks a winner, the loser is retained with `status='conflicting'` (never deleted or overwritten), and a `ConflictResolutionLog` entry records which sources disagreed, which rule applied, and when.

**Consequences:** Every disagreement is visible and explainable after the fact — a reviewer or auditor can see exactly why a number was chosen. Requires maintaining source-priority configuration per field type as new sources are added, which is a deliberate, small operational cost in exchange for auditability.

---

### ADR-007: OCR Confidence Modeled Separately from Source and Extraction Confidence

**Status:** Accepted

**Context:** Many RERA filings are scanned PDFs. Conflating "this source is authoritative" with "this scan OCR'd cleanly" would misrepresent data quality — a poorly-scanned authoritative filing is not the same problem as an inherently low-trust source.

**Decision:** Track three distinct confidence dimensions per OCR-derived DataPoint — `source_confidence` (trust in the source itself), `ocr_confidence` (the OCR engine's own confidence), `extraction_confidence` (template/anchor match quality of the field parser) — combined via a documented, configurable formula into a `composite_confidence`.

**Consequences:** Confidence scores remain meaningful and explainable even as OCR quality varies filing-to-filing. Adds modeling complexity (three fields instead of one) — justified given confidence scoring is a first-class auditability requirement, not a nice-to-have.

---

### ADR-008: Provider-Agnostic LLM Interface ("Report Language Adapter")

**Status:** Accepted

**Context:** MVP uses Groq and/or Gemini; the product requirement explicitly anticipates swapping to Anthropic Claude later. Locking report generation to one provider's SDK would make that swap a rewrite rather than a config change.

**Decision:** A `LLMProvider` interface (`generate(prompt: PromptSpec) -> LLMResponse`) abstracts the provider. `GroqProvider`/`GeminiProvider` implement it now; `ClaudeProvider` is a pure addition later with zero caller changes. Provider selection is configuration-driven.

**Consequences:** Same adapter-pattern philosophy applied consistently across the whole system (data sources and LLM alike), which keeps the architecture coherent. Opens the door cheaply to per-section provider choice or automatic failover later, though that's not built for MVP.

---

### ADR-009: Mandatory, Blocking Numeric-Traceability Guardrail on All LLM Output

**Status:** Accepted

**Context:** "The LLM must never calculate or invent data" is a stated principle with no enforcement mechanism unless something actually checks the LLM's output. Without this, the principle is a policy statement, not a system property.

**Decision:** After each section is generated, a deterministic parser extracts every numeric claim from the text, normalizes it, and matches it against the flattened, already-persisted Report JSON for that version. Unmatched numbers trigger a bounded automatic regeneration; persistent failure sets `guardrail_status=FAILED` and blocks the report from advancing past Draft.

**Consequences:** This is the concrete mechanism that makes anti-hallucination enforceable rather than aspirational — it is intentionally blocking, even at the cost of occasional regeneration latency, because the alternative (an advisory-only check) would allow an ungrounded number into an IC report. Known limitation, accepted and documented rather than solved here: this catches numeric hallucination mechanically; qualitative overreach (unsupported sentiment) is mitigated only by prompt design and the human Review step.

---

### ADR-010: Draft → Analyst Review → Published as a Server-Enforced State Machine, DB-Level Publish Immutability

**Status:** Accepted

**Context:** IC reports are audit-sensitive deliverables. Without a governed lifecycle, "the report" is just a mutable document with no tamper-evidence or history.

**Decision:** Report state transitions are enforced server-side (permission + current-status validity checked together, invalid transitions rejected loudly). Published `ReportVersion` rows are immutable, enforced at both the application layer and the database layer (a trigger/policy rejecting any UPDATE where `OLD.status='published'`). Regeneration always creates a new version; prior versions are retained and comparable.

**Consequences:** Tamper-evidence and full history are structural guarantees, not just conventions the application layer happens to follow — the database-level enforcement is deliberate belt-and-suspenders given this is a compliance requirement. Reviewers approve/reject but do not directly edit content, preserving genuine two-person control.

---

### ADR-011: Celery + Redis for Async Orchestration, Postgres as the Durable Status Source of Truth

**Status:** Accepted

**Context:** Acquisition, OCR, forecasting, LLM generation, and PDF rendering are all slow, potentially-flaky operations that must not block the request/response cycle. The confirmed stack is Python/FastAPI, and Celery is its natural async task framework.

**Decision:** Celery workers (organized into per-queue pools: discovery, acquisition per source-type, OCR, analytics, scenario/risk, reports/LLM, PDF) handle all async work, with Redis as broker + result backend + shared state store (rate limits, circuit breakers). Critically, **job/run status is always read from Postgres rows**, never from the Celery result backend — so a Redis restart loses only in-flight scheduling, not history, and status is recoverable/re-derivable.

**Consequences:** Straightforward to operate at MVP scale; per-queue pools mean one blocked source (circuit open) doesn't starve unrelated work. Flagged for revisit, not acted on now: if backlog durability/ordering guarantees become critical at larger scale, Celery's broker abstraction allows swapping toward SQS/Azure Service Bus without a redesign.

---

### ADR-012: India Region for Storage/Compute; LLM Calls Carry Structured JSON Only

**Status:** Accepted

**Context:** RERA and financial data are sensitive and the product requires India data residency. Groq and Gemini, the confirmed MVP LLM providers, do not guarantee India-region processing for API calls.

**Decision:** All persistent data (database, object storage) and application compute reside in an India cloud region (e.g. AWS ap-south-1 / Azure Central India). The data-residency requirement is scoped to storage and compute, not to LLM inference calls — LLM calls only ever receive the already-computed, validated structured Report JSON for prose generation, never raw scraped documents or the underlying source PII. This scoping was an explicit product decision, not an architectural default.

**Consequences:** Keeps Groq/Gemini usable for MVP as chosen, while keeping the actual sensitive dataset (raw filings, documents, DataPoints) fully within India-region infrastructure. Flagged as a compliance item to revisit if the company's legal/compliance function later determines the residency requirement should extend further — the Report Language Adapter abstraction (ADR-008) means that change would be a provider swap, not a redesign.

---

### ADR-013: Self-Hosted OCR as MVP Default

**Status:** Accepted (revisit if accuracy is insufficient)

**Context:** Scanned RERA filings need OCR. Cloud OCR vendor APIs are an option but add another third party receiving scanned government filings, in some tension with the residency-conscious posture established in ADR-012, plus per-page cost.

**Decision:** Use self-hosted OCR (Tesseract/PaddleOCR) as the MVP default, behind an `OCRProvider` interface so a managed, region-pinned alternative (e.g. a region-locked managed OCR service) can be substituted later without touching the ingestion pipeline.

**Consequences:** No per-page vendor cost, no additional third party touching scanned filings, consistent with the residency posture. Risk, explicitly flagged and not yet resolved: self-hosted OCR accuracy on real MahaRERA scan quality is unvalidated — Milestone M3 in the roadmap exists specifically to validate this before it's load-bearing, with a region-pinned managed OCR service as the documented fallback.

---

### ADR-014: Manual Overrides as First-Class `DataPoint`s, Not a Parallel Correction Table

**Status:** Accepted

**Context:** Analysts will need to correct bad or missing adapter data. A separate "corrections" table would mean two different code paths for reading "what's the current value of this field" — one that checks overrides, one that doesn't — which is a durable source of bugs.

**Decision:** A manual correction is an ordinary `DataPoint` row whose source is a reserved `manual_override` DataSource, with a companion `ManualOverrideDetail` row (user, reason, previous value linked, optional reviewer sign-off for critical fields). It flows through the exact same versioning/conflict-resolution/audit machinery as any other DataPoint.

**Consequences:** One unified history and read path for every fact regardless of provenance — no special-casing required in Analytics or Report Assembly to "check for overrides." The override is fully traceable in the same version chain as adapter-sourced data, just distinguishably tagged.

---

### ADR-015: Report-Generation Data Completeness/Staleness Gating Defaults to Block-with-Logged-Override

**Status:** Accepted

**Context:** Real adapter data will often be incomplete or stale by the time a report is needed. A hard, unconditional block would make the system unusable in common real-world conditions; silently proceeding with stale/incomplete data would violate the "never silently drop data" principle.

**Decision:** Report generation checks required fields against configured staleness/completeness thresholds and blocks by default, listing exactly which fields are missing or stale — but an Analyst may explicitly override and proceed, with that decision logged (who, when, which fields were stale/missing at the time).

**Consequences:** Balances real-world data gaps against auditability — nothing proceeds silently, but the system doesn't become unusable when a source is temporarily degraded. The override is visible in the resulting report's audit trail, not hidden.

---

### ADR-016: Reports Must Disclose Resolved Data Conflicts, Not Just Present the Winning Value

**Status:** Accepted

**Context:** ADR-006 resolves cross-source disagreements deterministically so calculations have a single number to work with, and M2's real conflict-resolution behavior confirmed this works (MahaRERA vs. Developer Website disagreeing on Lodha Park's unit count, 450 vs. 460). But resolving a conflict for internal calculation purposes is a different concern from what the Investment Committee is shown — a report that silently prints "450 units" gives the IC false confidence that the figure is uncontested, when in fact two sources disagreed and a policy picked a side.

**Decision:** The Report Assembly Service includes a `discrepancy` block in `generated_json` for every field the report uses that has an open `ConflictResolutionLog` entry — winning value + source, losing value(s) + source(s), and the rule applied. The Key Assumptions section's prompt is required to disclose this explicitly rather than presenting only the resolved figure. Because the disclosed losing value is a deliberate, sourced part of the report text, it must also be added to the guardrail's (ADR-009) reference set of traceable numbers — otherwise a correctly-disclosed losing figure would look identical to an invented one and get wrongly blocked.

**Consequences:** The IC sees genuine data disagreements instead of false precision, directly extending the explainability/auditability principles to the report layer, not just the database layer. Requires the guardrail's reference-set construction to be conflict-aware (union of resolved + disclosed-rejected values) rather than a naive flatten of only the "current" values — a detail that would be an easy, silent correctness gap to introduce later if this ADR weren't recorded.
