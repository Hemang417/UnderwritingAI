# IC Intelligence Platform — Demo UI

A Streamlit front-end over the FastAPI backend, built for walking someone through
the platform end-to-end: discover a project, acquire data, run forecasts and
scenarios, generate an AI report under the guardrail, then review/publish it
with a downloadable PDF.

This is a **demo client**, not a production UI — it talks to the same API
everything else in this repo talks to, over plain HTTP.

## Running it

1. Backend must be reachable (Postgres + Redis via Docker, API via local
   `uvicorn` since the Docker `api` image predates the `groq`/`fpdf2`
   dependencies added in M7/M8):

   ```
   docker compose up -d postgres redis worker
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. Start the UI:

   ```
   pip install -r streamlit_app/requirements.txt
   streamlit run streamlit_app/app.py
   ```

   Opens at `http://localhost:8501`.

## Demo accounts

Two fixed accounts are pre-seeded in the dev database so there's no
registration fumbling live on a call. Both use the "Quick demo login"
buttons in the sidebar.

| Role     | Email                          | Password        |
|----------|---------------------------------|------------------|
| Analyst  | analyst-demo@example.com        | BoardDemo!2026   |
| Reviewer | boardroom-reviewer@example.com  | BoardDemo!2026   |

An Analyst cannot approve their own report (enforced server-side) — the demo
walkthrough switches accounts in Tab 6 to show the two-person control working.

## Suggested walkthrough (~5 minutes)

1. **Discover** — search "Lodha Park", point out the resolved canonical ID.
2. **Acquire Data** — run acquisition, point out the RERA-vs-developer-site
   unit count disagreement and that the losing value is retained, not dropped.
3. **Forecast** — run it, show the pricing chart and risk breakdown.
4. **Scenarios** — run it, show the Bear/Base/Bull fan chart.
5. **Generate Report** — trigger it (real Groq call, ~1 minute), then expand
   **Key Assumptions** — the LLM explicitly discloses the data disagreement
   with both values, sources, and the rule applied. This is the core "AI
   can't hallucinate or hide a discrepancy" story.
6. **Review & Publish** — submit as Analyst, switch to Reviewer in the
   sidebar, approve, download the PDF. Mention publish immutability is
   enforced at the database level, not just the API.

## Live MAHARERA lookup (Tab 1, "Search live on MAHARERA")

Adds a project that isn't in the seeded database yet, by looking it up live
on MAHARERA's own public API by **project name**. This is separate from the
fixture-backed data that powers the rest of the demo, and has a real
operational dependency:

- **Requires a session token a human obtained by solving a CAPTCHA.**
  There is no automated way to get one, by design. From the project root,
  run:

  ```
  python scripts/setup_maharera_session.py
  ```

  This opens a visible Chrome window -- solve the CAPTCHA yourself within
  90 seconds. The token is saved to `config/maharera_token.json`
  automatically (gitignored, never committed); no `.env` edit or app
  restart needed, the live adapter reads it fresh on the very next lookup.
  First run needs Playwright's browser binary installed once:
  `playwright install chromium`.
- **The token lasts ~100 minutes.** After that, live lookups fail with a
  502 and a message to refresh it -- just re-run
  `python scripts/setup_maharera_session.py`. Existing projects
  (fixture-backed, like Lodha Park) are completely unaffected either way.
- **Search is by project name only.** MAHARERA's live search has no
  reliable way to look up a project by RERA registration number alone --
  its search filters server-side by name, and a bounded scan of the
  unfiltered project list essentially never lands on an arbitrary project
  (confirmed in practice, not just in theory). So registration-number
  search isn't offered here; if a project's exact name isn't known, look
  it up on MAHARERA's own site first.
- **What gets saved, and what doesn't.** A successful lookup permanently
  creates a new `CanonicalProject` row (name, developer, city, locality,
  status, RERA registration number, plus MAHARERA's own internal
  `project_id`) -- a real database record from that point on. It does
  *not* pull `possession_date` into the versioned acquisition system as
  part of this step -- that requires running **Acquire Data** (Tab 2)
  afterward, which correctly routes a live-resolved project to the real
  live adapter (not the fixture one -- seeded demo projects are
  unaffected either way, they keep using the fixture).
- **`unit_count` and pricing will still be missing.** MAHARERA's own API
  simply doesn't expose either field (confirmed by inspecting every
  available endpoint), and there's no live "developer website" adapter --
  that source stays fixture-only. So Acquire Data alone won't fully
  complete a live-resolved project; **Generate Report** will hard-block
  with a 409 until `unit_count` and `current_price_per_sqft` are filled
  in some other way. Use the **Manual Override** section in Tab 2 for
  this -- it's a first-class, audited `DataPoint` (not a hack), takes
  effect immediately, and `unit_count` additionally requires a Reviewer's
  sign-off afterward (switch accounts and paste in the override ID shown
  after submitting).

## Notes

- Report generation uses the real Groq API (same key as the backend's
  `.env`) — expect ~40-70 seconds for all 11 sections.
- `st.session_state` (current project, current report version) persists
  across login/logout within the same browser tab, which is what makes the
  analyst-to-reviewer handoff in Tab 6 work without re-navigating.
- If the backend isn't reachable, every tab shows a clear error rather than
  a raw stack trace.
