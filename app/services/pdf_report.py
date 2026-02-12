"""Generate a professional PDF report from the JSON report content."""

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

BRAND_COLOR = colors.HexColor("#4F46E5")
BRAND_LIGHT = colors.HexColor("#EEF2FF")
GRAY_600 = colors.HexColor("#4B5563")
GRAY_400 = colors.HexColor("#9CA3AF")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(
        ParagraphStyle(
            "ReportTitle",
            parent=ss["Heading1"],
            fontSize=18,
            textColor=BRAND_COLOR,
            spaceAfter=4 * mm,
        )
    )
    ss.add(
        ParagraphStyle(
            "SectionTitle",
            parent=ss["Heading2"],
            fontSize=13,
            textColor=BRAND_COLOR,
            spaceBefore=6 * mm,
            spaceAfter=3 * mm,
            borderWidth=0,
        )
    )
    ss.add(
        ParagraphStyle(
            "BodyText2",
            parent=ss["BodyText"],
            fontSize=10,
            leading=14,
            textColor=GRAY_600,
        )
    )
    ss.add(
        ParagraphStyle(
            "SmallGray",
            parent=ss["BodyText"],
            fontSize=8,
            textColor=GRAY_400,
        )
    )
    ss.add(
        ParagraphStyle(
            "BulletItem",
            parent=ss["BodyText"],
            fontSize=10,
            leading=14,
            textColor=GRAY_600,
            leftIndent=12,
            bulletIndent=0,
            bulletFontSize=10,
        )
    )
    ss.add(
        ParagraphStyle(
            "Quote",
            parent=ss["BodyText"],
            fontSize=9,
            leading=13,
            textColor=GRAY_600,
            leftIndent=12,
            borderPadding=4,
            fontName="Helvetica-Oblique",
        )
    )
    return ss


def _score_color(score: int | float) -> colors.Color:
    if score >= 80:
        return colors.HexColor("#16A34A")
    if score >= 60:
        return colors.HexColor("#CA8A04")
    return colors.HexColor("#DC2626")


def generate_pdf(content: dict) -> bytes:
    """Build a PDF from a report JSON dict. Returns raw PDF bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    ss = _styles()
    story: list = []

    # --- Header ---
    title = content.get("title", "Rapport d'evaluation")
    story.append(Paragraph(title, ss["ReportTitle"]))

    position = content.get("position", "")
    date_str = content.get("date", datetime.now(timezone.utc).strftime("%d/%m/%Y"))
    story.append(Paragraph(f"{position} &mdash; {date_str}", ss["SmallGray"]))
    story.append(Spacer(1, 6 * mm))

    # --- Scores table ---
    scores = content.get("scores", {})
    if scores:
        story.append(Paragraph("Scores", ss["SectionTitle"]))
        labels = {
            "global": "Global",
            "technical": "Technique",
            "experience": "Experience",
            "communication": "Communication",
        }
        data = [["", "Score"]]
        for key, label in labels.items():
            val = scores.get(key, "-")
            if isinstance(val, (int, float)):
                data.append([label, f"{val}/100"])
            else:
                data.append([label, str(val)])

        t = Table(data, colWidths=[6 * cm, 3 * cm])
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_LIGHT),
            ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_COLOR),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]
        for i, row in enumerate(data[1:], 1):
            try:
                val = int(row[1].replace("/100", ""))
                style_cmds.append(("TEXTCOLOR", (1, i), (1, i), _score_color(val)))
                style_cmds.append(("FONTNAME", (1, i), (1, i), "Helvetica-Bold"))
            except (ValueError, AttributeError):
                pass
        t.setStyle(TableStyle(style_cmds))
        story.append(t)
        story.append(Spacer(1, 4 * mm))

    # --- Summary ---
    summary = content.get("summary", "")
    if summary:
        story.append(Paragraph("Synthese", ss["SectionTitle"]))
        story.append(Paragraph(summary, ss["BodyText2"]))

    # --- Strengths ---
    strengths = content.get("strengths", [])
    if strengths:
        story.append(Paragraph("Points forts", ss["SectionTitle"]))
        for s in strengths:
            story.append(Paragraph(f"&bull; {s}", ss["BulletItem"]))

    # --- Areas to explore ---
    areas = content.get("areas_to_explore", [])
    if areas:
        story.append(Paragraph("Points a approfondir", ss["SectionTitle"]))
        for a in areas:
            story.append(Paragraph(f"&bull; {a}", ss["BulletItem"]))

    # --- Skills assessment ---
    skills = content.get("skills_assessment", [])
    if skills:
        story.append(Paragraph("Evaluation des competences", ss["SectionTitle"]))
        data = [["Competence", "Niveau", "Evidence"]]
        for sk in skills:
            data.append(
                [
                    str(sk.get("skill", "")),
                    str(sk.get("level", "")),
                    str(sk.get("evidence", ""))[:80],
                ]
            )
        t = Table(data, colWidths=[4 * cm, 3 * cm, 10 * cm])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND_LIGHT),
                    ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_COLOR),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(t)

    # --- Key quotes ---
    quotes = content.get("key_quotes", [])
    if quotes:
        story.append(Paragraph("Verbatims", ss["SectionTitle"]))
        for q in quotes:
            story.append(Paragraph(f'"{q}"', ss["Quote"]))
            story.append(Spacer(1, 2 * mm))

    # --- Disclaimer ---
    meta = content.get("metadata", {})
    disclaimer = meta.get(
        "disclaimer",
        "Ce rapport est genere par IA a titre informatif. "
        "Il ne constitue pas une recommandation d'embauche.",
    )
    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(
            f"<i>{disclaimer}</i>",
            ss["SmallGray"],
        )
    )
    duration = meta.get("interview_duration", "")
    questions = meta.get("questions_count", "")
    if duration or questions:
        story.append(
            Paragraph(
                f"Duree: {duration} | Questions: {questions} | "
                f"Genere par {meta.get('generated_by', 'AIHM')}",
                ss["SmallGray"],
            )
        )

    doc.build(story)
    return buf.getvalue()
