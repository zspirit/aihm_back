"""Generate a professional PDF report from the JSON report content.

Enhanced single-page layout with score bars, info box, branded header/footer.
"""

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics import renderPDF

# --- Brand palette ---
BRAND_COLOR = colors.HexColor("#4F46E5")
BRAND_LIGHT = colors.HexColor("#EEF2FF")
BRAND_DARK = colors.HexColor("#3730A3")
GRAY_800 = colors.HexColor("#1F2937")
GRAY_600 = colors.HexColor("#4B5563")
GRAY_400 = colors.HexColor("#9CA3AF")
GRAY_200 = colors.HexColor("#E5E7EB")
GRAY_100 = colors.HexColor("#F3F4F6")
GREEN = colors.HexColor("#16A34A")
GREEN_LIGHT = colors.HexColor("#DCFCE7")
ORANGE = colors.HexColor("#CA8A04")
ORANGE_LIGHT = colors.HexColor("#FEF9C3")
RED = colors.HexColor("#DC2626")
RED_LIGHT = colors.HexColor("#FEE2E2")
WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN = 1.5 * cm
CONTENT_W = PAGE_W - 2 * MARGIN

FOOTER_TEXT = (
    "Genere par AIHM -- Ce rapport est un outil d'aide a la decision. "
    "La decision finale revient au recruteur."
)


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle(
        "Brand",
        parent=ss["Heading1"],
        fontSize=14,
        textColor=BRAND_COLOR,
        spaceAfter=1 * mm,
        leading=16,
    ))
    ss.add(ParagraphStyle(
        "CompanyName",
        parent=ss["Normal"],
        fontSize=8,
        textColor=GRAY_400,
        spaceAfter=2 * mm,
    ))
    ss.add(ParagraphStyle(
        "SectionTitle",
        parent=ss["Heading2"],
        fontSize=9,
        textColor=BRAND_COLOR,
        spaceBefore=3 * mm,
        spaceAfter=1.5 * mm,
        leading=11,
    ))
    ss.add(ParagraphStyle(
        "Body8",
        parent=ss["BodyText"],
        fontSize=8,
        leading=10,
        textColor=GRAY_600,
    ))
    ss.add(ParagraphStyle(
        "Body8Bold",
        parent=ss["BodyText"],
        fontSize=8,
        leading=10,
        textColor=GRAY_800,
        fontName="Helvetica-Bold",
    ))
    ss.add(ParagraphStyle(
        "SmallGray",
        parent=ss["BodyText"],
        fontSize=6.5,
        textColor=GRAY_400,
        leading=8,
    ))
    ss.add(ParagraphStyle(
        "BulletItem",
        parent=ss["BodyText"],
        fontSize=8,
        leading=10,
        textColor=GRAY_600,
        leftIndent=8,
        bulletIndent=0,
    ))
    ss.add(ParagraphStyle(
        "Quote",
        parent=ss["BodyText"],
        fontSize=7.5,
        leading=9.5,
        textColor=GRAY_600,
        leftIndent=8,
        fontName="Helvetica-Oblique",
    ))
    ss.add(ParagraphStyle(
        "StrengthItem",
        parent=ss["BodyText"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#15803D"),
        leftIndent=8,
    ))
    ss.add(ParagraphStyle(
        "WeaknessItem",
        parent=ss["BodyText"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#B45309"),
        leftIndent=8,
    ))
    return ss


def _score_color(score: int | float) -> colors.Color:
    if score >= 70:
        return GREEN
    if score >= 50:
        return ORANGE
    return RED


def _score_bg(score: int | float) -> colors.Color:
    if score >= 70:
        return GREEN_LIGHT
    if score >= 50:
        return ORANGE_LIGHT
    return RED_LIGHT


def _make_score_bar(label: str, score: int | float, bar_width: float = 120) -> Drawing:
    """Draw a colored horizontal score bar with label and value."""
    d = Drawing(CONTENT_W, 14)
    # Label
    d.add(String(0, 3, label, fontSize=8, fontName="Helvetica", fillColor=GRAY_600))
    # Bar background
    bar_x = 90
    d.add(Rect(bar_x, 2, bar_width, 10, fillColor=GRAY_200, strokeColor=None, strokeWidth=0))
    # Bar fill
    fill_w = max(1, bar_width * min(score, 100) / 100)
    fill_color = _score_color(score)
    d.add(Rect(bar_x, 2, fill_w, 10, fillColor=fill_color, strokeColor=None, strokeWidth=0))
    # Score text
    d.add(String(
        bar_x + bar_width + 6, 3,
        f"{int(score)}/100",
        fontSize=8,
        fontName="Helvetica-Bold",
        fillColor=fill_color,
    ))
    return d


def _section_divider():
    """Thin colored line to separate sections."""
    d = Drawing(CONTENT_W, 3)
    d.add(Rect(0, 1, CONTENT_W, 0.8, fillColor=BRAND_LIGHT, strokeColor=None, strokeWidth=0))
    return d


def _add_footer(canvas, doc):
    """Draw footer on every page with page number and disclaimer."""
    canvas.saveState()
    canvas.setFont("Helvetica", 6)
    canvas.setFillColor(GRAY_400)
    canvas.drawString(MARGIN, 12 * mm, FOOTER_TEXT)
    canvas.drawRightString(PAGE_W - MARGIN, 12 * mm, f"Page {doc.page}")
    # Top line for footer area
    canvas.setStrokeColor(GRAY_200)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 16 * mm, PAGE_W - MARGIN, 16 * mm)
    canvas.restoreState()


def generate_pdf(content: dict) -> bytes:
    """Build a PDF from a report JSON dict. Returns raw PDF bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=20 * mm,
    )
    ss = _styles()
    story: list = []

    # ===== HEADER: AIHM brand + tenant company =====
    meta = content.get("metadata", {})
    company_name = content.get("company_name", meta.get("company_name", ""))

    story.append(Paragraph("AIHM", ss["Brand"]))
    if company_name:
        story.append(Paragraph(company_name, ss["CompanyName"]))

    # ===== KEY INFORMATION BOX =====
    candidate_name = content.get("title", "Rapport d'evaluation")
    position = content.get("position", "")
    date_str = content.get("date", datetime.now(timezone.utc).strftime("%d/%m/%Y"))
    duration = meta.get("interview_duration", "")
    questions_count = meta.get("questions_count", "")

    info_data = [[
        Paragraph(f"<b>Candidat:</b> {candidate_name}", ss["Body8"]),
        Paragraph(f"<b>Poste:</b> {position}", ss["Body8"]),
    ], [
        Paragraph(f"<b>Date:</b> {date_str}", ss["Body8"]),
        Paragraph(
            f"<b>Duree:</b> {duration}"
            + (f" | <b>Questions:</b> {questions_count}" if questions_count else ""),
            ss["Body8"],
        ),
    ]]
    info_table = Table(info_data, colWidths=[CONTENT_W / 2] * 2)
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 3 * mm))

    # ===== SCORES with colored bars =====
    scores = content.get("scores", {})
    if scores:
        story.append(_section_divider())
        story.append(Paragraph("Scores", ss["SectionTitle"]))

        score_labels = {
            "global": "Global",
            "technical": "Technique",
            "experience": "Experience",
            "communication": "Communication",
        }
        for key, label in score_labels.items():
            val = scores.get(key)
            if val is not None and isinstance(val, (int, float)):
                story.append(_make_score_bar(label, val))
        story.append(Spacer(1, 2 * mm))

    # ===== SUMMARY =====
    summary = content.get("summary", "")
    if summary:
        story.append(_section_divider())
        story.append(Paragraph("Synthese", ss["SectionTitle"]))
        story.append(Paragraph(summary, ss["Body8"]))

    # ===== STRENGTHS with checkmarks =====
    strengths = content.get("strengths", [])
    if strengths:
        story.append(_section_divider())
        story.append(Paragraph("Points forts", ss["SectionTitle"]))
        for s in strengths:
            # Unicode checkmark with green color
            story.append(Paragraph(
                f'<font color="#16A34A">\u2713</font>&nbsp; {s}',
                ss["StrengthItem"],
            ))

    # ===== AREAS TO EXPLORE with X marks =====
    areas = content.get("areas_to_explore", [])
    if areas:
        story.append(_section_divider())
        story.append(Paragraph("Points a approfondir", ss["SectionTitle"]))
        for a in areas:
            # Unicode ballot X with orange color
            story.append(Paragraph(
                f'<font color="#B45309">\u2717</font>&nbsp; {a}',
                ss["WeaknessItem"],
            ))

    # ===== SKILLS TABLE with alternating rows =====
    skills = content.get("skills_assessment", [])
    if skills:
        story.append(_section_divider())
        story.append(Paragraph("Evaluation des competences", ss["SectionTitle"]))

        data = [["Competence", "Niveau", "Evidence"]]
        for sk in skills:
            data.append([
                str(sk.get("skill", "")),
                str(sk.get("level", "")),
                str(sk.get("evidence", ""))[:90],
            ])

        col_widths = [3.5 * cm, 2.5 * cm, CONTENT_W - 6 * cm]
        t = Table(data, colWidths=col_widths)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_COLOR),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("LEADING", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.3, GRAY_200),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        # Alternating row colors
        for i in range(1, len(data)):
            bg = GRAY_100 if i % 2 == 0 else WHITE
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
        t.setStyle(TableStyle(style_cmds))
        story.append(t)

    # ===== KEY QUOTES =====
    quotes = content.get("key_quotes", [])
    if quotes:
        story.append(_section_divider())
        story.append(Paragraph("Verbatims", ss["SectionTitle"]))
        for q in quotes:
            story.append(Paragraph(f'\u00ab {q} \u00bb', ss["Quote"]))
            story.append(Spacer(1, 1 * mm))

    # ===== DISCLAIMER =====
    disclaimer = meta.get(
        "disclaimer",
        "Ce rapport est genere par IA a titre informatif. "
        "Il ne constitue pas une recommandation d'embauche.",
    )
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"<i>{disclaimer}</i>", ss["SmallGray"]))

    doc.build(story, onFirstPage=_add_footer, onLaterPages=_add_footer)
    return buf.getvalue()
