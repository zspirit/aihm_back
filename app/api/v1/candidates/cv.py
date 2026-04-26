import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_tenant_id, require_role
from app.models.candidate import Candidate
from app.models.user import User

router = APIRouter(tags=["candidates"])


def _generate_anonymized_pdf(anon_data: dict) -> bytes:
    """Genere un PDF avec les donnees CV anonymisees."""
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=40, bottomMargin=40, leftMargin=50, rightMargin=50)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle("AnonTitle", parent=styles["Heading1"], fontSize=18, textColor=colors.HexColor("#A52B8E"))
    section_style = ParagraphStyle("AnonSection", parent=styles["Heading2"], fontSize=13, textColor=colors.HexColor("#333333"), spaceBefore=16, spaceAfter=8)
    body_style = ParagraphStyle("AnonBody", parent=styles["Normal"], fontSize=10, leading=14)
    small_style = ParagraphStyle("AnonSmall", parent=styles["Normal"], fontSize=9, textColor=colors.grey, leading=12)

    # Header
    elements.append(Paragraph(anon_data.get("anonymous_id", "Candidat anonyme"), title_style))
    elements.append(Paragraph("CV Anonymise — AIHM", small_style))
    elements.append(Spacer(1, 16))

    # Summary
    if anon_data.get("summary"):
        elements.append(Paragraph("Profil", section_style))
        elements.append(Paragraph(anon_data["summary"], body_style))
        elements.append(Spacer(1, 8))

    # Experience
    if anon_data.get("experience_years"):
        elements.append(Paragraph(f"Experience totale : {anon_data['experience_years']} ans", body_style))

    exps = anon_data.get("experiences", [])
    if exps:
        elements.append(Paragraph("Experiences professionnelles", section_style))
        for exp in exps:
            title = exp.get("title", "")
            company = exp.get("company", "")
            duration = exp.get("duration", "")
            elements.append(Paragraph(f"<b>{title}</b> — {company} ({duration})", body_style))
            for resp in (exp.get("responsibilities") or [])[:5]:
                elements.append(Paragraph(f"  • {resp}", small_style))
            elements.append(Spacer(1, 6))

    # Education
    edus = anon_data.get("education", [])
    if edus:
        elements.append(Paragraph("Formation", section_style))
        for edu in edus:
            degree = edu.get("degree", "")
            field = edu.get("field", "")
            institution = edu.get("institution", "")
            year = edu.get("year", "")
            elements.append(Paragraph(f"<b>{degree}</b> {field} — {institution} ({year})", body_style))
        elements.append(Spacer(1, 8))

    # Skills
    skills = anon_data.get("skills", [])
    if skills:
        elements.append(Paragraph("Competences", section_style))
        skill_names = [s if isinstance(s, str) else s.get("name", "") for s in skills]
        elements.append(Paragraph(" • ".join(skill_names), body_style))
        elements.append(Spacer(1, 8))

    # Languages
    langs = anon_data.get("languages", [])
    if langs:
        elements.append(Paragraph("Langues", section_style))
        lang_texts = [f"{l.get('name', '')} ({l.get('level', '')})" if isinstance(l, dict) else str(l) for l in langs]
        elements.append(Paragraph(" • ".join(lang_texts), body_style))

    doc.build(elements)
    return buf.getvalue()


@router.get("/candidates/{candidate_id}/cv/download")
async def download_cv(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Telecharge le CV original d'un candidat depuis MinIO."""
    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    if not candidate.cv_file_path:
        raise HTTPException(status_code=404, detail="Aucun CV disponible pour ce candidat")
    if candidate.is_anonymized:
        from app.services.cv_anonymizer import anonymize_candidate_data
        anon_data = anonymize_candidate_data(str(candidate.id), candidate.cv_parsed_data or {})
        pdf_content = _generate_anonymized_pdf(anon_data)
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="cv_anonymise_{anon_data["anonymous_id"].replace(" ", "_").replace("#", "")}.pdf"'},
        )
    try:
        from app.services.storage import download_file
        parts = candidate.cv_file_path.split("/", 1)
        if len(parts) != 2:
            raise HTTPException(status_code=500, detail="Chemin CV invalide")
        content = await asyncio.get_event_loop().run_in_executor(
            None, download_file, parts[0], parts[1]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du telechargement: {str(e)}")
    filename = (candidate.cv_parsed_data or {}).get(
        "original_filename",
        f"{candidate.name.replace(' ', '_') if candidate.name else 'cv'}.pdf",
    )
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/candidates/{candidate_id}/reprocess-cv")
async def reprocess_cv(
    candidate_id: UUID,
    position_id: str | None = Query(None, description="Position to score against (optional)"),
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Re-trigger CV analysis for a candidate. If position_id provided, score against that position."""
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.cv_file_path:
        raise HTTPException(status_code=400, detail="Aucun fichier CV associe a ce candidat")

    celery_ok = False
    try:
        from app.workers.cv_processing import process_cv

        process_cv.delay(str(candidate.id), position_id)
        celery_ok = True
    except Exception:
        pass

    if not celery_ok:
        import asyncio as _asyncio
        from starlette.concurrency import run_in_threadpool

        cid = str(candidate.id)
        pid = position_id

        async def _run_inline():
            try:
                from app.workers.cv_processing import process_cv as _pvc
                await run_in_threadpool(_pvc, cid, pid)
            except Exception as exc:
                import structlog
                structlog.get_logger().warning("inline_reprocess_error", candidate_id=cid, error=str(exc))

        _asyncio.create_task(_run_inline())

    return {"status": "ok", "message": "Analyse CV relancee"}
