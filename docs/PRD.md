# Product Requirements Document

## Investment Committee Intelligence Platform

**Status:** Approved for architecture (v1.0)
**Owner:** Real Estate Asset Management Company — Internal Platform
**Document type:** PRD (reviewed and revised — see §14 Revision Notes for what changed from the original draft and why)

---

## 1. Purpose & Vision

Automate the production of Investment Committee (IC) reports for residential real estate investments, replacing manual, analyst-authored underwriting memos with a platform that is **deterministic, auditable, and reproducible** at its core, and uses AI **only** to convert validated structured data into professional report prose.

This is explicitly **not**:
- A web scraper (scraping is a means, not the product).
- A chatbot or general-purpose AI research assistant.
- A system where AI makes or influences financial judgments.

It **is**:
- A deterministic real-estate underwriting engine.
- A system where every number in a report can be traced back to a source, a timestamp, a confidence level, and a version.
- A system where the LLM's only job is writing, never arithmetic or data retrieval.

## 2. Product Principles

These are non-negotiable design constraints, not aspirations. Every architectural decision downstream must be checked against them.

1. **Never hallucinate data.** If a fact isn't in the validated dataset, it cannot appear in a report.
2. **Never calculate financial models using an LLM.** All arithmetic happens in deterministic engines before the LLM is invoked.
3. **Every number must be reproducible.** Given the same inputs and configuration version, every calculation must produce an identical result.
4. **Every assumption must be configurable.** No hardcoded constants in forecasting or ranking logic — assumptions live in versioned configuration.
5. **Every calculation must be explainable.** Each engine documents its inputs, method, and validation rules.
6. **Every report must be auditable.** Every report version, every data correction, and every state transition is logged.
7. **Every data point must store:** Source, Timestamp (fetched and effective-as-of), Confidence, Version.
8. **All forecasting models must be deterministic** — meaning *reproducible given fixed inputs and configuration*, not a claim that forecasts are accurate. Real estate appreciation is inherently uncertain; determinism is about traceability, not prediction quality. (See §12 for why this distinction matters and how it's enforced.)
9. **AI is the presentation layer, not the decision engine.**

## 3. Users & Roles

*(Gap identified in the original draft: no access model was defined. Resolved below — this is a hard requirement, not an implementation detail.)*

| Role | Can do | Cannot do |
|---|---|---|
| **Analyst** | Search/resolve projects, trigger data acquisition, generate reports, edit Draft report content, submit for review, manually override data points (with logged reason) | Approve/publish a report, edit source-of-truth config |
| **Reviewer** (Senior Analyst) | Approve or reject a report in review (send back with comments) | Directly edit report content while reviewing (preserves two-person control — see §11) |
| **Admin** | Configure adapters, ranking weights, scenario assumption defaults, manage users/roles | Author or approve reports by default (must be separately granted those roles if one person needs to do both) |

Authentication must support local accounts at launch and be structured so enterprise SSO (e.g. Azure AD, Google Workspace) can be added later without reworking downstream authorization logic.

## 4. Core Workflow

```
User enters Project Name (+ optional City)
        ↓
Project Discovery Service → Candidate Discovery → Candidate Ranking
        ↓
User Confirmation (only shown if multiple candidates exceed the confidence threshold)
        ↓
Project Resolution → Canonical Project Identifier
        ↓
Data Acquisition Orchestrator → Data Normalization (incl. conflict resolution)
        ↓
Database
        ↓
Analytics Layer (Pricing / Sales Velocity / Risk / Financial Forecast Engines)
        ↓
Scenario Engine (Bear / Base / Bull)
        ↓
LLM Report Generator → Guardrail Validation
        ↓
Draft → Analyst Review → Published Investment Committee Report
        ↓
PDF Export
```

## 5. Project Identity

Project names are **not** permanent identifiers. Every project has a canonical identity:

- State
- RERA Registration Number
- Developer
- Project Name

Once resolved, every downstream service uses the **Canonical Project ID**. The original free-text search string is never used again after resolution — it is retained only in search-history/audit records, not as a working identifier.

## 6. Project Discovery Engine

Responsibilities: search, rank, return candidates. Explicitly **out of scope** for this component: deciding which project is correct, financial logic, report generation, forecasting, or scraping entire RERA websites wholesale — it only locates the requested project.

## 7. Candidate Ranking

Deterministic, configurable weighted scoring across: exact project name match, fuzzy name similarity, city, state, locality, developer, RERA registration number, historical user selections, and other metadata. Weights are configuration, not code — changing ranking behavior must never require a deployment.

## 8. User Confirmation

If multiple candidates exceed the confidence threshold, the system **never** auto-selects. The analyst is shown, per candidate: Project Name, Developer, Locality, City, State, RERA Registration Number, Confidence Score, Current Status. Downstream processing begins only after explicit analyst selection.

## 9. Search History

Confirmed selections (`search string → canonical project ID`) persist. A future search matching a prior confirmed mapping offers **Use Previous Selection** or **Search Again**, rather than re-running discovery/ranking from scratch.

## 10. Data Acquisition

Every external source is an adapter behind a common interface — no exceptions, including future paid sources:

```
search_project()
get_project()
get_documents()
get_progress()
get_inventory()
get_quarterly_reports()
```

Adapters contain **no business logic** — they retrieve and return structured data only. Sequencing, retries, prioritization, and failure handling belong to the orchestrator, not the adapter.

Adapter categories: RERA (per-state), Developer Website, Market Data, Infrastructure, News, Government Data, Future Paid Data Sources.

**MVP scope:** MahaRERA is the only state adapter built initially. The adapter interface and orchestration/normalization logic must generalize to other states without modification — validated by building a second, minimal stub adapter early (see roadmap in the SAD) purely to prove the contract isn't overfit to Maharashtra's data shape.

### 10.1 Adapter & Orchestrator Failure Handling
*(Gap in the original draft: no failure-mode strategy was defined at the orchestration level. Resolved:)*

- Retries use exponential backoff, bounded attempts, and distinguish retryable errors (timeout, 5xx, 429) from non-retryable ones (404, CAPTCHA wall, auth failure).
- A circuit breaker opens per data source after repeated failures, marks that source degraded, and alerts an Admin — it does not silently keep retrying a dead source.
- Rate limiting and polite-crawling behavior (respecting crawl-delay, caching unchanged responses) are required for every adapter touching a government or developer website, both operationally and as risk mitigation (see §13).
- Partial data is not treated as failure or as success — it flows through with its actual completeness recorded, and report generation is gated by the staleness/completeness policy (§10.2), not by a binary success/fail flag.

### 10.2 Data Freshness & Staleness Policy
*(New requirement.)* Every field type has a configured maximum age. A report may not be generated using a field past its staleness threshold without an explicit, logged analyst override. Quarterly-filing-derived fields are re-checked on a schedule aligned to expected filing windows, not on a blanket re-crawl cadence.

## 11. Data Normalization & Conflict Resolution

All adapters output a common schema. Analytics engines must never know which state or source supplied a given fact.

*(Gap in the original draft: no policy existed for when two sources disagree. Resolved:)* When two sources disagree on the same field (e.g., unit count from a RERA filing vs. a developer website), a deterministic, configurable source-priority rule per field type resolves the conflict. The losing value is **never** silently averaged or dropped — it is retained with a `conflicting` status and the resolution is logged (which sources disagreed, which rule applied, when).

### 11.1 Manual Override & Correction
*(Gap in the original draft: no correction workflow existed for analyst-identified bad data. Resolved:)* An analyst can override any data point. The override is stored with the same auditability as any other data point — source tagged as manual, plus who made the change, when, and why, with the previous value retained and linked, not overwritten.

### 11.2 Discrepancy Disclosure in Reports
*(New requirement.)* Resolving a conflict internally (§11) so a deterministic engine has a single number to calculate with does not mean the disagreement disappears from what the Investment Committee sees. Any field used in a generated report that had a logged source disagreement must be explicitly disclosed — the value used, the value(s) rejected, their respective sources, and the rule that decided between them — not silently presented as one clean, unremarkable number. This is a mandatory input to Report Generation (§13), not an optional embellishment left to the LLM's discretion.

## 12. Analytics Layer

Fully independent of the acquisition/scraping layer. Each engine below is deterministic and documents its own **Inputs, Outputs, Dependencies, Mathematical model, Validation rules, and Failure modes** (detailed per-engine specs live in the SAD, not this PRD, to keep this document stable as engine internals evolve).

### 12.1 Pricing Forecast Engine
Forecasts over 1 / 3 / 5 / 7 / 10-year horizons. Inputs: current PSF, historical appreciation, comparable pricing, supply, demand, developer premium, infrastructure impact, inflation, interest rates. Outputs: nominal and real pricing, year-wise, in Bear/Base/Bull variants. No AI involvement in calculation.

### 12.2 Sales Velocity Forecast Engine
Forecasts units sold, inventory remaining, absorption, and sell-through timeline, in Bear/Base/Bull variants, incorporating inflation and macro assumptions.

### 12.3 Financial Forecast Engine
Derives investment-relevant financial outputs (returns, cash flow implications) from the above, under the same scenario variants.

### 12.4 Scenario Engine
Applies configurable assumption changes — inflation, interest rates, demand, supply, construction delays, developer execution, infrastructure timelines, pricing growth, sales velocity — to produce Bear/Base/Bull outputs. No hardcoded constants; every assumption is a versioned configuration value.

### 12.5 Risk Engine
Produces deterministic scores for Construction, Developer, Market, Demand, Execution, Pricing, and Regulatory risk, each with a documented, explainable methodology.

### 12.6 On Determinism
"Deterministic" throughout this document means: *given the same input data version and the same configuration version, the engine reproduces byte-identical output.* It does **not** mean the forecast will be accurate — real estate markets are uncertain, and no engine claims otherwise. This distinction must be visible to IC readers (e.g., in the report's Key Assumptions section) so determinism is never mistaken for a guarantee.

## 13. Report Generation

The Report Generator receives **structured JSON only**. It never searches the internet, never calculates a value, and never alters a deterministic output.

Sections produced: Executive Summary, Project Overview, Developer Analysis, Market Analysis, Pricing Analysis, Sales Velocity Analysis, Scenario Analysis, Risk Assessment, Key Assumptions, Investment Recommendation, Conclusion.

**LLM provider:** built behind a provider-agnostic interface. MVP targets Groq and/or Gemini; Anthropic Claude may be added later with no change to any calling code. Only the already-computed, validated structured JSON is sent to the LLM — no raw scraped documents, no PII beyond what's already in the structured facts.

### 13.1 Anti-Hallucination Guardrail
*(Gap in the original draft: "the LLM must never calculate or invent data" was a stated principle with no enforcement mechanism. Resolved:)* Every generated section undergoes a mandatory, blocking post-generation check: every number appearing in the text must be traceable back to the frozen input JSON for that report version. Unmatched numbers trigger a bounded automatic correction attempt; persistent failure blocks the report from advancing past Draft and is surfaced to the analyst. This is the concrete mechanism that makes Principle 1 (§2) enforceable rather than aspirational.

### 13.2 Discrepancy Disclosure
*(New requirement, see §11.2.)* For every field the report uses that has a logged conflict, the JSON handed to the LLM carries both the resolved value and the rejected value(s) with their sources and the rule applied. The Key Assumptions section must state this explicitly (e.g., "Unit count per MahaRERA: 450; per developer marketing materials: 460 — RERA figure used per source-priority policy"), not just print the resolved figure as though no disagreement existed. Because the rejected value is deliberately included in the report text, it must also be added to the guardrail's (§13.1) set of traceable numbers — otherwise a correctly-disclosed rejected figure would look like an invented one and get wrongly blocked.

## 14. Report Lifecycle & Versioning

*(Gap in the original draft: reports were described as an output, not as a versioned, governed artifact. Resolved:)*

Reports move through **Draft → Analyst Review → Published**:
- **Draft**: generated (and analyst-edited) content, editable.
- **Analyst Review**: submitted for a Reviewer's approval. The Reviewer approves or sends back with comments — the Reviewer does not directly edit content, preserving two-person control over what reaches the IC.
- **Published**: immutable. Any later regeneration (due to new data or a corrected data point) creates a **new version**; published versions are never edited in place, and prior versions remain available for comparison.

## 15. Non-Functional Requirements

*(Gap in the original draft: no NFRs were specified, despite driving nearly every infrastructure decision. Resolved, sized for the confirmed initial scale target — multiple offices, dozens of analysts, hundreds of tracked projects:)*

- Report generation (from trigger to Draft-ready) should complete within a few minutes under normal load; acquisition/OCR-heavy first-time project ingestion is expected to take longer and is explicitly asynchronous.
- The system supports concurrent report generation and data acquisition across multiple analysts/offices without cross-contamination of in-flight work.
- Data volume assumption for MVP sizing: hundreds of tracked projects, growing as additional state adapters are added.
- All persistent data (project data, reports, audit logs) resides in an India data region.

## 16. Security & Compliance

- Access control follows the role model in §3; every state-changing action (data override, report state transition, config change) is recorded in an append-only audit log.
- Published reports are immutable at both the application and database level.
- Data residency: stored data (database, object storage) resides in an India cloud region. LLM API calls carry only structured report JSON, not raw documents — data-residency scope is storage/compute, not third-party LLM inference, per explicit product decision.
- **Legal risk flag** *(new — not in the original draft):* scraping government and developer websites carries ToS/legal risk independent of engineering controls. Each data source requires a recorded legal-review sign-off before activation; the adapter framework's rate-limiting and caching are a technical mitigation, not a substitute for that review.

## 17. MVP Scope

**In scope for MVP:**
- MahaRERA adapter only (interface generalized for future states).
- Free/public data sources only (no paid market-data vendor integrations).
- Local authentication (email/password).
- Draft → Analyst Review → Published workflow.
- All five analytics engines, Scenario Engine, Risk Engine.
- LLM report generation on Groq/Gemini with the numeric-traceability guardrail.
- PDF export.

**Explicitly out of scope for MVP** (designed for, not built):
- Additional state RERA adapters beyond Maharashtra.
- Paid market-data vendor adapters (no existing subscriptions to build against).
- Enterprise SSO (local auth only at launch; SSO is additive later).
- Multi-office scoping/permissions beyond the base role model.
- Claude as an LLM provider (interface supports it; not wired at launch).

## 18. Revision Notes (from original draft)

This PRD was critically reviewed before architecture work began. The following gaps were identified in the original draft and are now reflected as explicit requirements above, rather than left implicit:

1. No auth/RBAC model → §3.
2. No report lifecycle/versioning → §14.
3. No conflict-resolution policy for disagreeing sources → §11.
4. No adapter/orchestrator failure-mode strategy → §10.1.
5. No manual-override/correction workflow → §11.1.
6. "Deterministic" conflated with "accurate" → §12.6.
7. No non-functional requirements → §15.
8. RERA portal heterogeneity understated as a risk → §10 (MVP scope note).
9. No LLM output guardrail mechanism → §13.1.
10. No legal/scraping risk flag → §16.
11. Resolved conflicts could silently disappear by the time they reached the IC → §11.2, §13.2. *(Added post-M2, after real conflict-resolution behavior was demonstrated and the user flagged the disclosure gap.)*

Full rationale for each is in the Architecture Decision Records (`ARD.md`); technical design is in the Software Architecture Document (`SAD.md`).
