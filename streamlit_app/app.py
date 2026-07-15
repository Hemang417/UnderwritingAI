import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="IC Intelligence Platform", layout="wide", page_icon="\U0001F3D7️")

DEFAULT_API_BASE = "http://127.0.0.1:8000"

for key, default in {
    "api_base": DEFAULT_API_BASE,
    "token": None,
    "user_email": None,
    "project": None,
    "report_version": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def api(method: str, path: str, **kwargs):
    url = st.session_state.api_base.rstrip("/") + path
    headers = kwargs.pop("headers", {})
    if st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    timeout = kwargs.pop("timeout", 120)
    try:
        return requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
    except requests.exceptions.ConnectionError:
        st.error(
            f"Could not reach the API at `{st.session_state.api_base}`. "
            "Is the backend running? (see sidebar to change the URL)"
        )
        st.stop()


def login(email: str, password: str) -> bool:
    resp = api("POST", "/auth/login", json={"email": email, "password": password})
    if resp.status_code == 200:
        data = resp.json()
        st.session_state.token = data["access_token"]
        st.session_state.user_email = email
        return True
    st.error(resp.json().get("detail", "Login failed"))
    return False


# ---------------------------------------------------------------- sidebar --
with st.sidebar:
    st.title("\U0001F3D7️ IC Intelligence Platform")
    st.caption("Deterministic underwriting. AI only writes the prose.")

    with st.expander("⚙️ Backend connection"):
        st.session_state.api_base = st.text_input("API base URL", value=st.session_state.api_base)

    st.divider()

    if st.session_state.token:
        st.success(f"Signed in as **{st.session_state.user_email}**")
        if st.button("Log out", use_container_width=True):
            st.session_state.token = None
            st.session_state.user_email = None
            st.rerun()
    else:
        st.subheader("Sign in")
        quick_tab, manual_tab = st.tabs(["Quick demo login", "Manual"])
        with quick_tab:
            st.caption("Pre-seeded demo accounts -- no setup needed.")
            if st.button("\U0001F464 Log in as Analyst", use_container_width=True):
                if login("analyst-demo@example.com", "BoardDemo!2026"):
                    st.rerun()
            if st.button("\U0001F50D Log in as Reviewer", use_container_width=True):
                if login("boardroom-reviewer@example.com", "BoardDemo!2026"):
                    st.rerun()
        with manual_tab:
            m_email = st.text_input("Email", key="manual_email")
            m_password = st.text_input("Password", type="password", key="manual_password")
            if st.button("Log in", key="manual_login"):
                if login(m_email, m_password):
                    st.rerun()

    if st.session_state.project:
        st.divider()
        st.caption("Current project")
        p = st.session_state.project
        st.write(f"**{p['project_name']}**")
        st.caption(f"{p['developer']} · {p['city']}")


# ------------------------------------------------------------------ main --
st.title("Investment Committee Intelligence Platform")
st.caption(
    "A deterministic real-estate underwriting pipeline. Every number is calculated by pure Python -- "
    "never guessed by an LLM. AI is used only to turn already-validated numbers into report prose, "
    "under a guardrail that mechanically blocks any invented figure before it reaches an analyst."
)

if not st.session_state.token:
    st.info("\U0001F448 Log in from the sidebar to begin (use the quick demo login for the fastest start).")
    st.stop()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    [
        "1 · Discover Project",
        "2 · Acquire Data",
        "3 · Forecast",
        "4 · Scenarios",
        "5 · Generate Report",
        "6 · Review & Publish",
    ]
)

# ---- 1. Discover ------------------------------------------------------
with tab1:
    st.header("Discover & Resolve Project Identity")
    st.write(
        "Search by name. A deterministic, config-driven ranking engine scores candidates and resolves "
        "to a stable canonical project ID -- everything downstream hangs off this one identity."
    )
    col1, col2, col3 = st.columns([3, 2, 1])
    query = col1.text_input("Project name", value="Lodha Park")
    city_hint = col2.text_input("City (optional)")
    col3.write("")
    col3.write("")
    search_clicked = col3.button("\U0001F50E Search", type="primary", use_container_width=True)

    if search_clicked:
        body = {"raw_text": query}
        if city_hint:
            body["city_hint"] = city_hint
        resp = api("POST", "/search", json=body)
        if resp.status_code == 200:
            data = resp.json()
            if data["status"] in ("resolved", "previous_mapping") and data["project"]:
                st.session_state.project = data["project"]
                st.session_state.report_version = None
                if data["status"] == "previous_mapping":
                    detail = "via a previously confirmed mapping"
                elif data.get("auto_confirmed"):
                    detail = "auto-confirmed -- ranking score cleared the threshold"
                else:
                    detail = "manually confirmed"
                st.success(f"Resolved to **{data['project']['project_name']}** ({detail})")
            elif data["status"] == "needs_confirmation":
                st.warning("Multiple candidates found -- pick one below:")
                for c in data["candidates"]:
                    label = f"{c['project_name']} — {c['city']} (score {c['confidence_score']})"
                    if st.button(label, key=f"cand-{c['id']}"):
                        st.session_state.project = c
                        st.session_state.report_version = None
                        st.rerun()
            else:
                st.error("No match found for that search.")
                st.info(
                    "Not in the database yet? Try a live MAHARERA lookup below -- it'll create a new "
                    "project record from real government registry data."
                )
        else:
            st.error(resp.text)

    with st.expander("\U0001F310 Search live on MAHARERA (for a project not already in the database)"):
        st.caption(
            "Looks the project up on MAHARERA's own public API and creates a new project record from "
            "real registry data -- name, developer, location, possession date. Requires a live session "
            "token (a human must have solved MAHARERA's CAPTCHA recently -- see streamlit_app/README.md) "
            "and can take several seconds. Search is by project name only -- MAHARERA's live search has "
            "no reliable way to look up a project by RERA registration number alone."
        )
        live_name = st.text_input("Project name", key="live_name")
        if st.button("\U0001F310 Search live on MAHARERA", key="live_search_btn"):
            if not live_name:
                st.warning("Enter a project name.")
            else:
                with st.spinner("Querying MAHARERA's live API..."):
                    live_resp = api("POST", "/search/live-maharera", json={"project_name": live_name})
                if live_resp.status_code == 200:
                    project = live_resp.json()
                    st.session_state.project = project
                    st.session_state.report_version = None
                    st.success(f"Found and resolved **{project['project_name']}** from live MAHARERA data.")
                elif live_resp.status_code == 404:
                    st.error(f"No matching project found on MAHARERA: {live_resp.json().get('detail')}")
                elif live_resp.status_code == 502:
                    st.error(
                        f"MAHARERA lookup failed: {live_resp.json().get('detail')} "
                        "(the session token may have expired -- ~100 minute lifetime)"
                    )
                else:
                    st.error(live_resp.text)

    if st.session_state.project:
        p = st.session_state.project
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Project", p["project_name"])
        c2.metric("Developer", p["developer"])
        c3.metric("City", p["city"])
        c4.metric("Status", p["status"].replace("_", " ").title())
        st.caption(f"RERA registration: `{p['rera_registration_number']}`  ·  Canonical ID: `{p['id']}`")

# ---- 2. Acquire ---------------------------------------------------------
with tab2:
    st.header("Data Acquisition & Conflict Resolution")
    if not st.session_state.project:
        st.info("Resolve a project in Tab 1 first.")
    else:
        project_id = st.session_state.project["id"]
        st.write("Pulls from every configured source (MahaRERA, developer website, ...) in parallel.")
        if st.button("\U0001F4E1 Run Acquisition", type="primary"):
            with st.spinner("Fetching from configured sources..."):
                resp = api("POST", f"/projects/{project_id}/acquire")
            if resp.status_code == 200:
                st.success("Acquisition complete.")
                for s in resp.json()["sources"]:
                    icon = "✅" if s["status"] == "success" else "⚠️"
                    fields = ", ".join(s["fields_written"]) or "—"
                    st.write(f"{icon} **{s['data_source_name']}** -- {s['status']} -- fields: {fields}")
            else:
                st.error(resp.text)

        resp = api("GET", f"/projects/{project_id}/data-points")
        if resp.status_code == 200:
            points = [d for d in resp.json() if d["is_current"]]
            if points:
                st.subheader("Current Data Points")
                df = pd.DataFrame(
                    [
                        {
                            "Field": d["field_name"],
                            "Value": d["value"],
                            "Source": d["source_name"],
                            "Status": d["status"],
                            "Confidence": d["composite_confidence"],
                        }
                        for d in points
                    ]
                )
                st.dataframe(df, use_container_width=True, hide_index=True)

                all_points = resp.json()
                conflicting = [d for d in all_points if d["status"] == "conflicting"]
                if conflicting:
                    st.warning(
                        "⚠️ **Source disagreement detected.** The losing value is never "
                        "silently averaged or dropped -- it's retained and will be explicitly "
                        "disclosed in the eventual report's Key Assumptions section."
                    )
                    # Repeated demo/test acquisitions can accumulate many historical
                    # conflict rows for the same field+value+source -- show each
                    # distinct disagreement once, not once per past acquisition run.
                    seen = set()
                    for d in conflicting:
                        key = (d["field_name"], d["value"], d["source_name"])
                        if key in seen:
                            continue
                        seen.add(key)
                        st.write(f"- `{d['field_name']}`: **{d['value']}** from {d['source_name']} (rejected)")

        st.divider()
        with st.expander("✏️ Manual Override (fill in a field no source could supply)"):
            st.caption(
                "Takes effect immediately, with a full audit trail (who, when, why). "
                "`unit_count` and `possession_date` additionally require a Reviewer's "
                "sign-off afterward (switch accounts below to record it); "
                "`current_price_per_sqft` doesn't. Common use case: a project resolved "
                "live from MAHARERA has no unit_count or pricing at all -- MAHARERA's "
                "API doesn't expose either -- so Forecast/Report generation need this "
                "filled in some other way."
            )
            oc1, oc2 = st.columns(2)
            override_field = oc1.selectbox(
                "Field", ["unit_count", "current_price_per_sqft", "possession_date"], key="override_field"
            )
            if override_field == "possession_date":
                override_value = oc2.date_input("Value", key="override_value_date")
            else:
                override_value = oc2.number_input("Value", key="override_value_num", step=1.0, format="%.2f")
            override_reason = st.text_input(
                "Reason (required -- kept in the audit trail)", key="override_reason"
            )
            if st.button("Submit override"):
                if not override_reason:
                    st.warning("A reason is required.")
                else:
                    value = (
                        override_value.isoformat()
                        if override_field == "possession_date"
                        else override_value
                    )
                    override_resp = api(
                        "POST",
                        f"/projects/{project_id}/data-points/{override_field}/override",
                        json={"value": value, "reason": override_reason},
                    )
                    if override_resp.status_code == 200:
                        data = override_resp.json()
                        if data["requires_review"]:
                            st.success(
                                f"Override applied immediately. Also requires a Reviewer's "
                                f"sign-off -- override ID: `{data['override_id']}`"
                            )
                        else:
                            st.success("Override applied immediately.")
                    else:
                        st.error(override_resp.text)

            st.write("**Reviewer sign-off** (for overrides on `unit_count`/`possession_date`)")
            rc1, rc2, rc3 = st.columns([2, 2, 1])
            review_id = rc1.text_input(
                "Override ID", key="review_override_id", label_visibility="collapsed",
                placeholder="Override ID",
            )
            review_notes = rc2.text_input(
                "Notes", key="review_notes", label_visibility="collapsed", placeholder="Notes (optional)"
            )
            with rc3:
                approve_clicked = st.button("✅ Approve", key="approve_override")
                reject_clicked = st.button("❌ Reject", key="reject_override")
            if approve_clicked or reject_clicked:
                if not review_id:
                    st.warning("Enter the override ID to review.")
                else:
                    review_resp = api(
                        "POST",
                        f"/data-point-overrides/{review_id}/review",
                        json={"approved": approve_clicked, "notes": review_notes or None},
                    )
                    if review_resp.status_code == 200:
                        if approve_clicked:
                            st.success("Recorded.")
                        else:
                            st.success(
                                "Rejection recorded (value not reverted -- submit a corrected override)."
                            )
                    else:
                        st.error(review_resp.text)

# ---- 3. Forecast ----------------------------------------------------------
with tab3:
    st.header("Deterministic Analytics Engines")
    if not st.session_state.project:
        st.info("Resolve a project first.")
    else:
        project_id = st.session_state.project["id"]
        st.write("Pricing, Sales Velocity, Financial, and Risk -- pure calculation, zero AI involvement.")
        if st.button("\U0001F4CA Run Forecast", type="primary"):
            with st.spinner("Running Pricing / Sales Velocity / Financial / Risk engines..."):
                resp = api("POST", f"/projects/{project_id}/forecast")
            if resp.status_code == 200:
                st.success("Forecast complete.")
            else:
                st.error(resp.text)

        resp = api("GET", f"/projects/{project_id}/forecast-runs")
        if resp.status_code == 200:
            runs = resp.json()
            latest: dict[str, dict] = {}
            for r in runs:
                latest.setdefault(r["engine_type"], r)  # API returns latest-first per engine

            if latest:
                cols = st.columns(4)
                pricing = latest.get("pricing")
                if pricing and pricing["status"] == "success":
                    rate = pricing["output"]["effective_annual_appreciation_rate_pct"]
                    cols[0].metric("Effective Appreciation", f"{rate}%")
                sv = latest.get("sales_velocity")
                if sv and sv["status"] == "success":
                    cols[1].metric("Sell-through (months)", sv["output"]["sell_through_timeline_months"])
                fin = latest.get("financial")
                if fin and fin["status"] == "success":
                    revenue = fin["output"]["total_revenue_potential_at_sellout"]
                    cols[2].metric("Revenue Potential", f"₹{revenue:,.0f}")
                risk = latest.get("risk")
                if risk:
                    cols[3].metric("Composite Risk (0-100)", risk["output"]["composite_risk_score"])

                if pricing and pricing["status"] == "success":
                    st.subheader("Pricing Forecast")
                    df = pd.DataFrame(pricing["output"]["horizons"]).set_index("year")
                    st.line_chart(df[["nominal_price_per_sqft", "real_price_per_sqft"]])

                if risk:
                    st.subheader("Risk Category Breakdown")
                    scores = risk["output"]["category_scores"]
                    df = pd.DataFrame({"score": scores})
                    st.bar_chart(df)
                    with st.expander("Category explanations (honest about missing data sources)"):
                        for category, explanation in risk["output"]["category_explanations"].items():
                            st.write(f"**{category.title()}**: {explanation}")
            else:
                st.info("No forecast runs yet -- click Run Forecast above.")

# ---- 4. Scenarios ----------------------------------------------------------
with tab4:
    st.header("Bear / Base / Bull Scenario Engine")
    if not st.session_state.project:
        st.info("Resolve a project first.")
    else:
        project_id = st.session_state.project["id"]
        st.write("Layers configurable, versioned assumption deltas on top of the base forecast.")
        if st.button("\U0001F3B2 Run Scenarios", type="primary"):
            with st.spinner("Applying Bear/Base/Bull assumption sets..."):
                resp = api("POST", f"/projects/{project_id}/scenarios")
            if resp.status_code == 200:
                st.success("Scenarios complete.")
            else:
                st.error(resp.text)

        resp = api("GET", f"/projects/{project_id}/scenario-results")
        if resp.status_code == 200:
            results = resp.json()
            latest: dict[str, dict] = {}
            for r in results:
                latest.setdefault(r["scenario_type"], r)  # API returns latest-first

            usable = {k: v for k, v in latest.items() if v["status"] == "success"}
            if usable:
                st.subheader("Nominal Price per Sqft by Scenario")
                chart = {}
                for scenario_type in ("bear", "base", "bull"):
                    if scenario_type in usable:
                        horizons = usable[scenario_type]["output"]["pricing"]["horizons"]
                        chart[scenario_type.title()] = {h["year"]: h["nominal_price_per_sqft"] for h in horizons}
                st.line_chart(pd.DataFrame(chart))

                cols = st.columns(3)
                for i, scenario_type in enumerate(("bear", "base", "bull")):
                    if scenario_type in usable:
                        risk_score = usable[scenario_type]["output"]["risk"]["composite_risk_score"]
                        cols[i].metric(f"{scenario_type.title()} Risk", risk_score)
            else:
                st.info("No scenario results yet -- run Forecast (Tab 3) first, then Run Scenarios above.")

# ---- 5. Generate Report -----------------------------------------------
with tab5:
    st.header("AI Report Generation + Anti-Hallucination Guardrail")
    if not st.session_state.project:
        st.info("Resolve a project first.")
    else:
        project_id = st.session_state.project["id"]
        st.write(
            "The LLM receives only already-computed, validated JSON -- it never calculates anything. "
            "Every number in the generated text is mechanically checked against that JSON afterward."
        )
        force = st.checkbox("Force past the completeness gate (proceed even if data is missing/stale)")
        if st.button("\U0001F4DD Generate Investment Committee Report", type="primary"):
            with st.spinner("Generating all 11 sections via the LLM, each guardrail-checked (~1 minute)..."):
                resp = api(
                    "POST",
                    f"/projects/{project_id}/reports/generate",
                    json={"force_override": force},
                )
            if resp.status_code == 200:
                st.session_state.report_version = resp.json()
                v = resp.json()
                st.success(f"Report v{v['version_number']} generated -- status: {v['status']}")
            elif resp.status_code == 409:
                st.warning("Completeness gate blocked generation:")
                st.json(resp.json()["detail"])
            else:
                st.error(resp.text)

        version = st.session_state.report_version
        if version:
            c1, c2, c3 = st.columns(3)
            c1.metric("Status", version["status"].title())
            c2.metric("Guardrail", (version["guardrail_status"] or "—").title())
            c3.metric("LLM Provider", version["llm_provider"])

            for s in version["sections"]:
                icon = "✅" if s["guardrail_status"] == "passed" else "❌"
                title = s["section_name"].replace("_", " ").title()
                with st.expander(f"{icon} {title}"):
                    st.write(s["generated_text"])
                    if s["section_name"] == "key_assumptions":
                        st.caption(
                            "\U0001F446 Any source disagreement is explicitly disclosed here with "
                            "both values, sources, and the rule applied -- never silently hidden."
                        )
                    if s["guardrail_status"] != "passed":
                        unmatched = s["guardrail_report"]["unmatched"]
                        st.error(f"Guardrail caught {len(unmatched)} unverifiable number(s):")
                        st.json(unmatched)

# ---- 6. Review & Publish -----------------------------------------------
with tab6:
    st.header("Two-Person Review & Publish")
    version = st.session_state.report_version
    if not version:
        st.info("Generate a report in Tab 5 first.")
    else:
        resp = api("GET", f"/report-versions/{version['id']}")
        if resp.status_code == 200:
            version = resp.json()
            st.session_state.report_version = version

        st.metric("Current status", version["status"].replace("_", " ").title())

        if version["status"] == "draft":
            st.write("An Analyst submits a Draft for a Reviewer's independent approval.")
            if st.button("\U0001F4E4 Submit for Review", type="primary"):
                resp = api("POST", f"/report-versions/{version['id']}/submit")
                if resp.status_code == 200:
                    st.session_state.report_version = resp.json()
                    st.rerun()
                else:
                    st.error(resp.json().get("detail", resp.text))

        elif version["status"] == "in_review":
            st.info(
                "Awaiting Reviewer decision. Switch to the **Reviewer** demo account in the sidebar -- "
                "an Analyst cannot approve their own report."
            )
            comments = st.text_area("Review comments (optional)")
            c1, c2 = st.columns(2)
            if c1.button("✅ Approve & Publish", type="primary"):
                resp = api(
                    "POST",
                    f"/report-versions/{version['id']}/review",
                    json={"approved": True, "comments": comments or None},
                )
                if resp.status_code == 200:
                    st.session_state.report_version = resp.json()
                    st.rerun()
                else:
                    st.error(resp.json().get("detail", resp.text))
            if c2.button("↩️ Reject (back to Draft)"):
                resp = api(
                    "POST",
                    f"/report-versions/{version['id']}/review",
                    json={"approved": False, "comments": comments or None},
                )
                if resp.status_code == 200:
                    st.session_state.report_version = resp.json()
                    st.rerun()
                else:
                    st.error(resp.json().get("detail", resp.text))

        elif version["status"] == "published":
            st.success(
                "\U0001F389 Published -- immutable from this point on, enforced by a database-level "
                "trigger, not just an application check."
            )
            pdf_resp = api("GET", f"/report-versions/{version['id']}/pdf")
            if pdf_resp.status_code == 200:
                st.download_button(
                    "⬇️ Download IC Report (PDF)",
                    data=pdf_resp.content,
                    file_name=f"IC_Report_v{version['version_number']}.pdf",
                    mime="application/pdf",
                )

            if version.get("supersedes_version_id"):
                st.caption(f"Supersedes version at `{version['supersedes_version_id']}`")

        st.divider()
        st.caption(
            "Regenerating (Tab 5) after publish always creates a new version -- the published row "
            "above is never edited in place, at either the application or database level."
        )
