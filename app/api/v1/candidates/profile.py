import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_tenant_id, require_role
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.analysis import Analysis
from app.models.user import User
from app.schemas.candidate import CandidateSummaryResponse
from app.services.audit import log_action
from app.services.cv_anonymizer import anonymize_candidate_data

router = APIRouter(tags=["candidates"])


@router.get("/candidates/{candidate_id}/competence-dossier")
async def download_competence_dossier(
    candidate_id: UUID,
    format: str = "pdf",
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Generate and download a dossier de competences (PDF or DOCX)."""
    if format not in ("pdf", "docx"):
        raise HTTPException(status_code=400, detail="Format invalide (pdf ou docx)")

    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    parsed = candidate.cv_parsed_data or {}
    if not parsed or parsed.get("parse_error"):
        raise HTTPException(status_code=400, detail="CV non analyse. Relancez l'analyse du CV.")

    data = {
        "name": parsed.get("name") or candidate.name or "Candidat",
        "email": parsed.get("email") or candidate.email,
        "phone": parsed.get("phone") or candidate.phone,
        "summary": parsed.get("summary", ""),
        "skills": parsed.get("skills", []),
        "experiences": parsed.get("experiences", []),
        "education": parsed.get("education", []),
        "languages": parsed.get("languages", []),
        "experience_years": parsed.get("experience_years"),
    }

    safe_name = (data["name"] or "candidat").replace(" ", "_")

    from app.services.competence_dossier import generate_dossier_pdf, generate_dossier_docx

    if format == "docx":
        content = generate_dossier_docx(data)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        filename = f"Dossier_competences_{safe_name}.docx"
    else:
        content = generate_dossier_pdf(data)
        media = "application/pdf"
        filename = f"Dossier_competences_{safe_name}.pdf"

    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/candidates/{candidate_id}/profile/compute")
async def compute_profile(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Calcule le profil intrinseque du candidat via Claude."""
    from starlette.concurrency import run_in_threadpool

    from app.services.profile_compute import compute_candidate_profile

    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.cv_parsed_data:
        raise HTTPException(
            status_code=400,
            detail="CV non analyse. Lancez d'abord l'analyse du CV.",
        )

    try:
        profile_data = await run_in_threadpool(
            compute_candidate_profile, candidate.cv_parsed_data
        )
    except ValueError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Erreur de parsing de la reponse Claude : {e}",
        )
    except Exception as e:
        import structlog
        _log = structlog.get_logger()
        _log.error("compute_profile_claude_error", candidate_id=str(candidate_id), error=str(e))
        raise HTTPException(
            status_code=502,
            detail="Erreur lors de l'appel a Claude. Veuillez reessayer.",
        )

    candidate.profile_score = profile_data.get("profile_score")
    candidate.profile_score_explanation = {
        "overall": profile_data.get("score_explanation", {}).get("overall", ""),
        "breakdown": profile_data.get("score_explanation", {}).get("breakdown", {}),
        "cv_quality_score": profile_data.get("cv_quality_score"),
        "cv_quality_details": profile_data.get("cv_quality_details", {}),
    }
    candidate.profile_competencies = profile_data.get("competencies", {})
    candidate.profile_suggestions = {
        "suggestions": profile_data.get("suggestions", []),
        "cv_quality_score": profile_data.get("cv_quality_score"),
        "cv_quality_details": profile_data.get("cv_quality_details", {}),
    }

    await log_action(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="compute_profile",
        entity_type="candidate",
        entity_id=str(candidate_id),
        details={"profile_score": candidate.profile_score},
    )

    await db.commit()
    await db.refresh(candidate)

    return {
        "candidate_id": str(candidate.id),
        "profile_score": candidate.profile_score,
        "profile_score_explanation": candidate.profile_score_explanation,
        "profile_competencies": candidate.profile_competencies,
        "profile_suggestions": candidate.profile_suggestions,
    }


@router.get("/candidates/{candidate_id}/profile/export")
async def export_profile_pdf(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Genere et retourne le dossier de competences PDF du candidat."""
    from datetime import datetime, timezone

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.graphics.shapes import Drawing, Rect, String

    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.profile_competencies and not candidate.cv_parsed_data:
        raise HTTPException(
            status_code=400,
            detail="CV non analyse. Relancez l'analyse du CV.",
        )

    BRAND_COLOR = colors.HexColor("#4F46E5")
    BRAND_LIGHT = colors.HexColor("#EEF2FF")
    GRAY_800 = colors.HexColor("#1F2937")
    GRAY_600 = colors.HexColor("#4B5563")
    GRAY_400 = colors.HexColor("#9CA3AF")
    GRAY_200 = colors.HexColor("#E5E7EB")
    GRAY_100 = colors.HexColor("#F3F4F6")
    GREEN = colors.HexColor("#16A34A")
    ORANGE = colors.HexColor("#CA8A04")
    RED = colors.HexColor("#DC2626")
    WHITE = colors.white

    PAGE_W, PAGE_H = A4
    MARGIN = 1.5 * cm
    CONTENT_W = PAGE_W - 2 * MARGIN

    FOOTER_TEXT = (
        "Genere par AIHM -- Dossier de competences. "
        "Ce document est un outil d'aide a la decision. La decision finale revient au recruteur."
    )

    ss = getSampleStyleSheet()

    def _add_style(name, parent_name, **kwargs):
        if name not in ss.byName:
            ss.add(ParagraphStyle(name, parent=ss[parent_name], **kwargs))

    _add_style("Brand", "Heading1", fontSize=14, textColor=BRAND_COLOR, spaceAfter=1 * mm, leading=16)
    _add_style("SectionTitle", "Heading2", fontSize=9, textColor=BRAND_COLOR,
               spaceBefore=3 * mm, spaceAfter=1.5 * mm, leading=11)
    _add_style("Body8", "BodyText", fontSize=8, leading=10, textColor=GRAY_600)
    _add_style("Body8Bold", "BodyText", fontSize=8, leading=10, textColor=GRAY_800, fontName="Helvetica-Bold")
    _add_style("SmallGray", "BodyText", fontSize=6.5, textColor=GRAY_400, leading=8)
    _add_style("BulletItem", "BodyText", fontSize=8, leading=10, textColor=GRAY_600, leftIndent=8)
    _add_style("PriorityHigh", "BodyText", fontSize=8, leading=10,
               textColor=colors.HexColor("#DC2626"), leftIndent=8)
    _add_style("PriorityMed", "BodyText", fontSize=8, leading=10,
               textColor=colors.HexColor("#CA8A04"), leftIndent=8)
    _add_style("PriorityLow", "BodyText", fontSize=8, leading=10,
               textColor=colors.HexColor("#4B5563"), leftIndent=8)

    def _score_color(score):
        if score >= 70:
            return GREEN
        if score >= 50:
            return ORANGE
        return RED

    def _make_score_bar(label, score, bar_width=120):
        d = Drawing(CONTENT_W, 14)
        d.add(String(0, 3, label, fontSize=8, fontName="Helvetica", fillColor=GRAY_600))
        bar_x = 110
        d.add(Rect(bar_x, 2, bar_width, 10, fillColor=GRAY_200, strokeColor=None, strokeWidth=0))
        fill_w = max(1, bar_width * min(float(score), 100) / 100)
        fill_color = _score_color(float(score))
        d.add(Rect(bar_x, 2, fill_w, 10, fillColor=fill_color, strokeColor=None, strokeWidth=0))
        d.add(String(bar_x + bar_width + 6, 3, f"{int(score)}/100",
                     fontSize=8, fontName="Helvetica-Bold", fillColor=fill_color))
        return d

    def _divider():
        d = Drawing(CONTENT_W, 3)
        d.add(Rect(0, 1, CONTENT_W, 0.8, fillColor=BRAND_LIGHT, strokeColor=None, strokeWidth=0))
        return d

    def _level_dots(level, max_level=5):
        filled = min(int(level), max_level)
        empty = max_level - filled
        return "\u25CF" * filled + "\u25CB" * empty

    def _add_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 6)
        canvas.setFillColor(GRAY_400)
        canvas.drawString(MARGIN, 12 * mm, FOOTER_TEXT)
        canvas.drawRightString(PAGE_W - MARGIN, 12 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(GRAY_200)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 16 * mm, PAGE_W - MARGIN, 16 * mm)
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=20 * mm,
    )
    story = []
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    competencies = candidate.profile_competencies or {}
    if not competencies and candidate.cv_parsed_data:
        parsed = candidate.cv_parsed_data
        competencies = {
            "technical": [{"name": s, "level": 3} if isinstance(s, str) else s for s in parsed.get("skills", [])],
            "experience": parsed.get("experiences", []),
            "education": parsed.get("education", []),
            "languages": [{"name": l, "level": "?"} if isinstance(l, str) else l for l in parsed.get("languages", [])],
        }
    score_expl = candidate.profile_score_explanation or {}
    if not score_expl and candidate.cv_score_explanation:
        score_expl = candidate.cv_score_explanation if isinstance(candidate.cv_score_explanation, dict) else {}
    suggestions_data = candidate.profile_suggestions or {}
    suggestions = suggestions_data.get("suggestions", [])
    cv_quality_score = suggestions_data.get("cv_quality_score")
    cv_quality_details = suggestions_data.get("cv_quality_details", {})
    breakdown = score_expl.get("breakdown", {})

    story.append(Paragraph("AIHM", ss["Brand"]))
    story.append(Spacer(1, 1 * mm))

    info_data = [
        [
            Paragraph(f"<b>Candidat :</b> {candidate.name}", ss["Body8"]),
            Paragraph(f"<b>Email :</b> {candidate.email or '—'}", ss["Body8"]),
        ],
        [
            Paragraph(f"<b>Telephone :</b> {candidate.phone or '—'}", ss["Body8"]),
            Paragraph(f"<b>Date du rapport :</b> {now_str}", ss["Body8"]),
        ],
    ]
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

    effective_score = candidate.profile_score if candidate.profile_score is not None else candidate.cv_score
    if effective_score is not None:
        story.append(_divider())
        score_label = "Score profil intrinseque" if candidate.profile_score is not None else "Score CV"
        story.append(Paragraph(score_label, ss["SectionTitle"]))
        story.append(_make_score_bar("Score global", effective_score))

        for dim_key, dim_label in [
            ("technical_depth", "Profondeur technique"),
            ("experience_quality", "Qualite de l'experience"),
            ("education_relevance", "Formation"),
            ("cv_completeness", "Completude du CV"),
        ]:
            dim_data = breakdown.get(dim_key, {})
            dim_score = dim_data.get("score")
            if dim_score is not None:
                story.append(_make_score_bar(dim_label, dim_score))

        if score_expl.get("overall"):
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(score_expl["overall"], ss["Body8"]))

        for dim_key, dim_label in [
            ("technical_depth", "Profondeur technique"),
            ("experience_quality", "Qualite de l'experience"),
            ("education_relevance", "Formation"),
            ("cv_completeness", "Completude du CV"),
        ]:
            dim_data = breakdown.get(dim_key, {})
            if dim_data.get("detail"):
                story.append(Paragraph(
                    f'<b>{dim_label} :</b> {dim_data["detail"]}', ss["Body8"]
                ))
        story.append(Spacer(1, 2 * mm))

    if cv_quality_score is not None:
        story.append(_divider())
        story.append(Paragraph("Qualite du document CV", ss["SectionTitle"]))
        story.append(_make_score_bar("Score qualite CV", cv_quality_score))
        for qkey, qlabel in [
            ("completeness", "Completude"),
            ("clarity", "Clarte"),
            ("impact", "Impact / chiffres"),
            ("consistency", "Coherence"),
        ]:
            qval = cv_quality_details.get(qkey)
            if qval is not None:
                story.append(_make_score_bar(qlabel, qval))
        story.append(Spacer(1, 2 * mm))

    technical = competencies.get("technical", [])
    if technical:
        story.append(_divider())
        story.append(Paragraph("Competences techniques", ss["SectionTitle"]))
        tech_header = [
            Paragraph("<b>Competence</b>", ss["Body8Bold"]),
            Paragraph("<b>Niveau</b>", ss["Body8Bold"]),
            Paragraph("<b>Demontre</b>", ss["Body8Bold"]),
            Paragraph("<b>Justification</b>", ss["Body8Bold"]),
        ]
        tech_data = [tech_header]
        for skill in technical:
            level = skill.get("level", 0)
            demonstrated = skill.get("demonstrated", False)
            dem_text = "\u2713 Oui" if demonstrated else "\u2717 Non"
            dem_color = "#16A34A" if demonstrated else "#DC2626"
            tech_data.append([
                Paragraph(f'<b>{skill.get("name", "")}</b>', ss["Body8Bold"]),
                Paragraph(_level_dots(level) + f" {level}/5", ss["Body8"]),
                Paragraph(f'<font color="{dem_color}">{dem_text}</font>', ss["Body8"]),
                Paragraph(str(skill.get("evidence", ""))[:100], ss["Body8"]),
            ])
        col_w = [2.8 * cm, 2.2 * cm, 2 * cm, CONTENT_W - 7 * cm]
        tech_table = Table(tech_data, colWidths=col_w)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_COLOR),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("LEADING", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.3, GRAY_200),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for i in range(1, len(tech_data)):
            bg = GRAY_100 if i % 2 == 0 else WHITE
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
        tech_table.setStyle(TableStyle(style_cmds))
        story.append(tech_table)
        story.append(Spacer(1, 2 * mm))

    soft_skills = competencies.get("soft_skills", [])
    if soft_skills:
        story.append(_divider())
        story.append(Paragraph("Competences comportementales observees", ss["SectionTitle"]))
        for ss_item in soft_skills:
            story.append(Paragraph(f"\u2022 {ss_item}", ss["BulletItem"]))
        story.append(Spacer(1, 2 * mm))

    experience = competencies.get("experience", [])
    if experience:
        story.append(_divider())
        story.append(Paragraph("Experience professionnelle", ss["SectionTitle"]))
        for exp in experience:
            duration = exp.get("duration_months", 0)
            years = duration // 12
            months = duration % 12
            dur_str = ""
            if years:
                dur_str += f"{years} an{'s' if years > 1 else ''}"
            if months:
                dur_str += f" {months} mois"
            if not dur_str:
                dur_str = "Duree non precisee"

            title_line = f'<b>{exp.get("title", "")}</b>'
            if exp.get("company"):
                title_line += f' — {exp["company"]}'
            if dur_str:
                title_line += f' <font color="#9CA3AF">({dur_str.strip()})</font>'
            story.append(Paragraph(title_line, ss["Body8Bold"]))

            for resp in (exp.get("responsibilities") or [])[:3]:
                story.append(Paragraph(f"\u2022 {resp}", ss["BulletItem"]))
            for ach in (exp.get("key_achievements") or [])[:2]:
                story.append(Paragraph(
                    f'<font color="#16A34A">\u2605</font> {ach}',
                    ss["BulletItem"],
                ))
            story.append(Spacer(1, 1.5 * mm))

    education = competencies.get("education", [])
    if education:
        story.append(_divider())
        story.append(Paragraph("Formation", ss["SectionTitle"]))
        for edu in education:
            year = edu.get("year", "")
            line = f'<b>{edu.get("degree", "")}</b>'
            if edu.get("field"):
                line += f' en {edu["field"]}'
            if edu.get("institution"):
                line += f' — {edu["institution"]}'
            if year:
                line += f' ({year})'
            story.append(Paragraph(line, ss["Body8"]))
        story.append(Spacer(1, 2 * mm))

    languages = competencies.get("languages", [])
    if languages:
        story.append(_divider())
        story.append(Paragraph("Langues", ss["SectionTitle"]))
        lang_items = [f'{lg.get("name", "")} : {lg.get("level", "")}' for lg in languages]
        story.append(Paragraph(" | ".join(lang_items), ss["Body8"]))
        story.append(Spacer(1, 2 * mm))

    if suggestions:
        story.append(_divider())
        story.append(Paragraph("Suggestions d'amelioration du CV", ss["SectionTitle"]))
        priority_labels = {"high": "PRIORITAIRE", "medium": "CONSEILLE", "low": "OPTIONNEL"}
        priority_colors = {
            "high": "#DC2626",
            "medium": "#CA8A04",
            "low": "#4B5563",
        }
        for sug in suggestions:
            priority = sug.get("priority", "low")
            category = sug.get("category", "")
            label = priority_labels.get(priority, priority.upper())
            color = priority_colors.get(priority, "#4B5563")
            text = (
                f'<font color="{color}"><b>[{label}]</b></font> '
                f'<i>{category}</i> — {sug.get("suggestion", "")}'
            )
            story.append(Paragraph(text, ss["BulletItem"]))
        story.append(Spacer(1, 2 * mm))

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "<i>Ce dossier de competences est genere par IA a titre informatif. "
        "Il ne constitue pas une recommandation d'embauche ou de rejet. "
        "La decision finale revient au recruteur.</i>",
        ss["SmallGray"],
    ))

    doc.build(story, onFirstPage=_add_footer, onLaterPages=_add_footer)
    pdf_bytes = buf.getvalue()

    safe_name = candidate.name.replace(" ", "_").replace("/", "_")
    filename = f"dossier_competences_{safe_name}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/candidates/{candidate_id}/summary",
    response_model=CandidateSummaryResponse,
)
async def get_candidate_summary(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Resume candidat 30 secondes — retourne le cache ou genere si absent."""
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    # Retourner le cache si disponible
    if candidate.summary_json:
        return CandidateSummaryResponse(
            candidate_id=str(candidate.id),
            candidate_name=candidate.name,
            **candidate.summary_json,
        )

    # Sinon generer et stocker
    if not candidate.cv_parsed_data:
        raise HTTPException(status_code=400, detail="CV non analyse.")

    summary = await _generate_and_store_summary(candidate, current_user, db)
    return CandidateSummaryResponse(
        candidate_id=str(candidate.id),
        candidate_name=candidate.name,
        **summary,
    )


@router.post(
    "/candidates/{candidate_id}/summary/generate",
    response_model=CandidateSummaryResponse,
)
async def regenerate_candidate_summary(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Force la regeneration du resume IA et le stocke en BD."""
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    if not candidate.cv_parsed_data:
        raise HTTPException(status_code=400, detail="CV non analyse.")

    summary = await _generate_and_store_summary(candidate, current_user, db)
    return CandidateSummaryResponse(
        candidate_id=str(candidate.id),
        candidate_name=candidate.name,
        **summary,
    )


@router.patch("/candidates/{candidate_id}/summary")
async def update_candidate_summary(
    candidate_id: UUID,
    payload: dict,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Met a jour le resume (edition inline du pitch, strengths, etc.)."""
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    current = candidate.summary_json or {}
    allowed_fields = {"pitch", "strengths", "concerns", "areas_to_dig", "red_flags", "key_questions", "overall_score", "recommendation"}
    for key, value in payload.items():
        if key in allowed_fields:
            current[key] = value
    candidate.summary_json = current
    await db.commit()
    return {"status": "ok"}


async def _generate_and_store_summary(candidate, current_user, db) -> dict:
    """Genere le resume via Claude et le stocke en BD."""
    from starlette.concurrency import run_in_threadpool
    from app.services.candidate_summary import generate_candidate_summary

    position_data = None
    if candidate.position_id:
        from app.models.position import Position
        pos_result = await db.execute(
            select(Position).where(Position.id == candidate.position_id)
        )
        position = pos_result.scalar_one_or_none()
        if position:
            position_data = {
                "title": position.title,
                "required_skills": position.required_skills,
                "seniority_level": position.seniority_level,
            }

    interview_data = None
    analysis_data = None
    interview_result = await db.execute(
        select(Interview)
        .where(
            Interview.candidate_id == candidate.id,
            Interview.tenant_id == current_user.tenant_id,
            Interview.status == "completed",
        )
        .order_by(Interview.ended_at.desc())
        .limit(1)
    )
    interview = interview_result.scalar_one_or_none()
    if interview:
        interview_data = {
            "status": interview.status,
            "duration_seconds": interview.duration_seconds,
            "questions_asked": interview.questions_asked,
        }
        analysis_result = await db.execute(
            select(Analysis).where(Analysis.interview_id == interview.id)
        )
        analysis = analysis_result.scalar_one_or_none()
        if analysis:
            analysis_data = {
                "scores": analysis.scores,
                "skills_extracted": analysis.skills_extracted,
                "communication_indicators": analysis.communication_indicators,
                "score_explanations": analysis.score_explanations,
            }

    candidate_dict = {
        "name": candidate.name,
        "cv_parsed_data": candidate.cv_parsed_data,
        "cv_score": candidate.cv_score,
        "profile_score": candidate.profile_score,
    }

    try:
        summary = await run_in_threadpool(
            generate_candidate_summary,
            candidate_dict,
            position_data,
            interview_data,
            analysis_data,
        )
    except Exception as e:
        import structlog
        structlog.get_logger().error("candidate_summary_error", candidate_id=str(candidate.id), error=str(e))
        raise HTTPException(status_code=502, detail="Erreur lors de la generation du resume.")

    # Stocker en BD
    candidate.summary_json = summary
    await db.commit()
    return summary


@router.get("/candidates/{candidate_id}/anonymized")
async def get_anonymized_candidate(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter", "viewer")),
    db: AsyncSession = Depends(get_db),
):
    """Retourne les donnees CV anonymisees du candidat."""
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.cv_parsed_data:
        raise HTTPException(
            status_code=400,
            detail="CV non analyse. Lancez d'abord l'analyse du CV.",
        )

    anonymized = anonymize_candidate_data(str(candidate.id), candidate.cv_parsed_data)
    return {
        "candidate_id": str(candidate.id),
        "is_anonymized": candidate.is_anonymized,
        "data": anonymized,
    }


@router.patch("/candidates/{candidate_id}/anonymize")
async def toggle_anonymize(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Active/desactive le mode anonymise pour un candidat."""
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    candidate.is_anonymized = not candidate.is_anonymized

    await log_action(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="toggle_anonymize",
        entity_type="candidate",
        entity_id=str(candidate_id),
        details={"is_anonymized": candidate.is_anonymized},
    )

    await db.commit()
    await db.refresh(candidate)

    return {
        "candidate_id": str(candidate.id),
        "is_anonymized": candidate.is_anonymized,
    }
