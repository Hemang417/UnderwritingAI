from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.discovery.models import CanonicalProject
from app.reporting.models import ReportSection

SECTION_TITLES = {
    "executive_summary": "Executive Summary",
    "project_overview": "Project Overview",
    "developer_analysis": "Developer Analysis",
    "market_analysis": "Market Analysis",
    "pricing_analysis": "Pricing Analysis",
    "sales_velocity_analysis": "Sales Velocity Analysis",
    "scenario_analysis": "Scenario Analysis",
    "risk_assessment": "Risk Assessment",
    "key_assumptions": "Key Assumptions",
    "investment_recommendation": "Investment Recommendation",
    "conclusion": "Conclusion",
}


def _pdf_safe(text: str) -> str:
    """fpdf2's core Helvetica font is Latin-1 only. Rather than bundling a
    Unicode TTF asset for this MVP, substitute the one non-Latin-1
    character this system's own guardrail is known to produce (Rupee
    sign) and fall back to a safe replacement for anything else --
    documented simplification, not a silent crash on real report text.
    """
    return text.replace("₹", "Rs. ").encode("latin-1", errors="replace").decode("latin-1")


def render_report_pdf(
    *, project: CanonicalProject, version_number: int, sections: list[ReportSection]
) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # multi_cell's default new_x/new_y leaves the cursor at the *right*
    # edge of the cell, not back at the left margin -- the next multi_cell
    # then computes zero available width and raises "Not enough
    # horizontal space to render a single character". Every call here
    # must explicitly reset to LMARGIN/NEXT.
    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(
        0, 10, _pdf_safe(f"{project.project_name} - Investment Committee Report"),
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )
    pdf.set_font("Helvetica", "", 11)
    subtitle = f"Version {version_number}  |  {project.developer.name}  |  {project.city}, {project.state}"
    pdf.multi_cell(0, 6, _pdf_safe(subtitle), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    by_name = {s.section_name: s for s in sections}
    for section_name, title in SECTION_TITLES.items():
        section = by_name.get(section_name)
        if section is None:
            continue
        pdf.set_font("Helvetica", "B", 13)
        pdf.multi_cell(0, 8, _pdf_safe(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, _pdf_safe(section.effective_text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)

    return bytes(pdf.output())
