"""Génération PDF d'un timesheet mensuel (EPIC F)."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_KAIROS = colors.HexColor("#D9532F")
_INK = colors.HexColor("#1A1710")
_LINE = colors.HexColor("#D6CCB4")
_PAPER2 = colors.HexColor("#F2ECDE")

_STATUS_FR = {"draft": "Brouillon", "submitted": "En validation", "approved": "Validé", "rejected": "Refusé"}


def _cell(v: float) -> str:
    return "½" if v == 0.5 else ("1" if v == 1 else "")


def build_timesheet_pdf(grid, consultant_name: str) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1 * cm, rightMargin=1 * cm, topMargin=1 * cm, bottomMargin=1 * cm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], fontSize=15, textColor=_KAIROS, spaceAfter=2)
    sub = ParagraphStyle("s", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#4A4438"))

    elems = [
        Paragraph(f"Compte rendu d'activité — {consultant_name}", title),
        Paragraph(f"{grid.label} &nbsp;·&nbsp; statut : <b>{_STATUS_FR.get(grid.status, grid.status)}</b>", sub),
        Spacer(1, 10),
    ]

    refs = [r for r in (list(grid.missions) + list(grid.absences)) if any(k.startswith(r.code + ":") for k in grid.cells)]
    header = ["Imputation"] + [str(d.d) for d in grid.days]
    table_data = [header]
    for r in refs:
        table_data.append([r.code] + [_cell(grid.cells.get(f"{r.code}:{d.d}", 0)) for d in grid.days])
    # ligne total/jour
    tot_row = ["Total / j"]
    for d in grid.days:
        t = sum(v for k, v in grid.cells.items() if k.split(":")[1] == str(d.d))
        tot_row.append(_cell(t) or (str(t).rstrip("0").rstrip(".") if t else ""))
    table_data.append(tot_row)

    ndays = len(grid.days)
    day_w = (25.7 - 3.5) / max(ndays, 1) * cm
    col_widths = [3.5 * cm] + [day_w] * ndays
    table = Table(table_data, colWidths=col_widths, repeatRows=1)

    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("GRID", (0, 0), (-1, -1), 0.3, _LINE),
        ("BACKGROUND", (0, 0), (-1, 0), _INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), _PAPER2),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]
    for i, d in enumerate(grid.days):
        if d.we:
            style.append(("BACKGROUND", (i + 1, 1), (i + 1, -2), colors.HexColor("#F7F4EC")))
    table.setStyle(TableStyle(style))
    elems.append(table)

    tt = grid.totals or {}
    elems.append(Spacer(1, 12))
    elems.append(Paragraph(
        f"Total travaillé : <b>{tt.get('worked', 0):g} j</b> &nbsp;·&nbsp; "
        f"Absences : <b>{tt.get('absence', 0):g} j</b> &nbsp;·&nbsp; "
        f"Facturable : <b>{round(tt.get('billable', 0)):,} €</b>".replace(",", " "), sub))

    doc.build(elems)
    return buf.getvalue()
