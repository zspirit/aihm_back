"""GDPR endpoints: candidate data access, portability, and erasure (token-based auth)."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.interview import Interview

router = APIRouter(tags=["gdpr"])


async def _get_candidate_by_token(token: str, db: AsyncSession) -> Candidate:
    """Resolve a candidate from a consent token. Raises 404 if invalid/expired."""
    result = await db.execute(
        select(Consent).where(
            Consent.token == token,
            Consent.granted.is_(True),
        )
    )
    consent = result.scalar_one_or_none()
    if not consent:
        raise HTTPException(status_code=404, detail="Token invalide ou expire")

    # Check expiration
    if consent.expires_at and consent.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Token invalide ou expire")

    cand_result = await db.execute(
        select(Candidate).where(Candidate.id == consent.candidate_id)
    )
    candidate = cand_result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    return candidate


@router.post("/candidates/me")
async def get_my_data(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """GDPR Art.15 — Right of access: return candidate's personal data."""
    candidate = await _get_candidate_by_token(token, db)

    # Fetch interviews
    interview_result = await db.execute(
        select(Interview).where(Interview.candidate_id == candidate.id)
    )
    interviews = interview_result.scalars().all()

    return {
        "candidate": {
            "id": str(candidate.id),
            "name": candidate.name,
            "email": candidate.email,
            "phone": candidate.phone,
            "cv_parsed_data": candidate.cv_parsed_data,
            "cv_score": candidate.cv_score,
            "profile_score": candidate.profile_score,
            "pipeline_status": candidate.pipeline_status,
            "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        },
        "interviews": [
            {
                "id": str(i.id),
                "status": i.status,
                "started_at": i.started_at.isoformat() if i.started_at else None,
                "ended_at": i.ended_at.isoformat() if i.ended_at else None,
                "duration_seconds": i.duration_seconds,
            }
            for i in interviews
        ],
        "scores": {
            "cv_score": candidate.cv_score,
            "cv_score_explanation": candidate.cv_score_explanation,
            "profile_score": candidate.profile_score,
            "profile_score_explanation": candidate.profile_score_explanation,
        },
    }


@router.delete("/candidates/me", status_code=204)
async def delete_my_data(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """GDPR Art.17 — Right to erasure: anonymize candidate and revoke consents."""
    candidate = await _get_candidate_by_token(token, db)

    from app.services.cv_anonymizer import anonymize_candidate_data

    # Anonymize candidate data
    anonymized = anonymize_candidate_data(str(candidate.id), candidate.cv_parsed_data)
    candidate.name = anonymized.get("anonymous_id", "Anonyme")
    candidate.email = None
    candidate.phone = None
    candidate.cv_parsed_data = anonymized
    candidate.cv_file_path = None
    candidate.summary_json = None
    candidate.feedback_json = None
    candidate.is_anonymized = True

    # Revoke all consents
    consent_result = await db.execute(
        select(Consent).where(Consent.candidate_id == candidate.id)
    )
    for consent in consent_result.scalars().all():
        consent.granted = False
        consent.revoked_at = datetime.now(timezone.utc)

    await db.commit()
    return None


@router.get("/candidates/me/portabilite")
async def export_my_data(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """GDPR Art.20 — Right to data portability: export all candidate data as JSON."""
    candidate = await _get_candidate_by_token(token, db)

    # Fetch interviews with related data
    interview_result = await db.execute(
        select(Interview).where(Interview.candidate_id == candidate.id)
    )
    interviews = interview_result.scalars().all()

    return {
        "candidate": {
            "id": str(candidate.id),
            "name": candidate.name,
            "email": candidate.email,
            "phone": candidate.phone,
            "cv_parsed_data": candidate.cv_parsed_data,
            "tags": candidate.tags,
            "notes": candidate.notes,
            "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        },
        "interviews": [
            {
                "id": str(i.id),
                "status": i.status,
                "scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
                "started_at": i.started_at.isoformat() if i.started_at else None,
                "ended_at": i.ended_at.isoformat() if i.ended_at else None,
                "duration_seconds": i.duration_seconds,
                "questions_asked": i.questions_asked,
            }
            for i in interviews
        ],
        "scores": {
            "cv_score": candidate.cv_score,
            "cv_score_explanation": candidate.cv_score_explanation,
            "profile_score": candidate.profile_score,
            "profile_score_explanation": candidate.profile_score_explanation,
        },
        "feedback_json": candidate.feedback_json,
    }
