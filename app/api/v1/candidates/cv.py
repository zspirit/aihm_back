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
        raise HTTPException(status_code=403, detail="Le CV original n'est pas disponible en mode anonymise")
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
