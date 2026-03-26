"""
Batch matching service — computes N*M match scores for positions x candidates.
Uses ai_score_matches (sync, Claude API) in batches of 20 candidates.
Called by Celery workers (sync context).
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.candidate import Candidate
from app.models.match_score import MatchScore, MatchSession
from app.models.position import Position
from app.services.matching import ai_score_matches

logger = structlog.get_logger()

BATCH_SIZE = 20


def _load_position_data(db: Session, position_id: uuid.UUID, tenant_id: uuid.UUID) -> dict | None:
    """Load a position and return as dict for AI scoring."""
    result = db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == tenant_id,
        )
    )
    position = result.scalar_one_or_none()
    if not position:
        return None
    return {
        "title": position.title,
        "description": position.description,
        "required_skills": position.required_skills or [],
        "seniority_level": position.seniority_level,
    }


def _load_candidates(
    db: Session,
    tenant_id: uuid.UUID,
    candidate_ids: list[uuid.UUID] | None = None,
) -> list[dict]:
    """Load candidates with parsed CV data as dicts for AI scoring."""
    query = select(Candidate, Position).join(
        Position, Candidate.position_id == Position.id
    ).where(
        Candidate.tenant_id == tenant_id,
        Candidate.cv_parsed_data.isnot(None),
    )
    if candidate_ids:
        query = query.where(Candidate.id.in_(candidate_ids))

    result = db.execute(query)
    rows = result.all()

    candidates = []
    for candidate, position in rows:
        candidates.append({
            "candidate_id": str(candidate.id),
            "name": candidate.name,
            "email": candidate.email,
            "source_position_id": str(position.id),
            "source_position_title": position.title,
            "cv_score": candidate.cv_score,
            "cv_parsed_data": candidate.cv_parsed_data or {},
        })
    return candidates


def _upsert_scores(
    db: Session,
    session: MatchSession,
    position_id: uuid.UUID,
    matches: list[dict],
) -> int:
    """Upsert match scores into DB using INSERT ON CONFLICT UPDATE."""
    if not matches:
        return 0

    now = datetime.now(timezone.utc)
    rows = []
    for match in matches:
        rows.append({
            "id": uuid.uuid4(),
            "tenant_id": session.tenant_id,
            "candidate_id": uuid.UUID(match["candidate_id"]),
            "position_id": position_id,
            "score": float(match.get("match_score", 0)),
            "reasons": match.get("match_reasons"),
            "computed_at": now,
        })

    if not rows:
        return 0

    stmt = pg_insert(MatchScore).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_match_candidate_position",
        set_={
            "score": stmt.excluded.score,
            "reasons": stmt.excluded.reasons,
            "computed_at": stmt.excluded.computed_at,
        },
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


def compute_batch_matching(session_id: str) -> None:
    """
    Main entry point for Celery worker.
    Loads session, computes all N*M pairs, upserts results.
    """
    from app.core.database import sync_session_factory

    with sync_session_factory() as db:
        # Load session
        result = db.execute(
            select(MatchSession).where(MatchSession.id == uuid.UUID(session_id))
        )
        session = result.scalar_one_or_none()
        if not session:
            logger.error("match_session_not_found", session_id=session_id)
            return

        # Mark as running
        session.status = "running"
        db.commit()

        tenant_id = session.tenant_id
        position_ids = [uuid.UUID(pid) for pid in (session.position_ids or [])]
        candidate_ids = (
            [uuid.UUID(cid) for cid in session.candidate_ids]
            if session.candidate_ids
            else None
        )

        # Load all candidates once
        all_candidates = _load_candidates(db, tenant_id, candidate_ids)
        if not all_candidates:
            session.status = "completed"
            session.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        total_computed = 0

        for position_id in position_ids:
            position_data = _load_position_data(db, position_id, tenant_id)
            if not position_data:
                logger.warning("position_not_found", position_id=str(position_id))
                continue

            # Process in batches of BATCH_SIZE
            for batch_start in range(0, len(all_candidates), BATCH_SIZE):
                batch = all_candidates[batch_start: batch_start + BATCH_SIZE]

                try:
                    matches = ai_score_matches(batch, position_data, limit=BATCH_SIZE)
                    upserted = _upsert_scores(db, session, position_id, matches)
                    total_computed += upserted

                    # Update progress
                    # Reload session to avoid stale state
                    db.refresh(session)
                    session.computed_pairs = total_computed
                    db.commit()

                    logger.info(
                        "batch_matching_progress",
                        session_id=session_id,
                        position_id=str(position_id),
                        batch_start=batch_start,
                        upserted=upserted,
                        total_computed=total_computed,
                    )

                except Exception as e:
                    logger.error(
                        "batch_matching_batch_error",
                        session_id=session_id,
                        position_id=str(position_id),
                        error=str(e),
                    )
                    # Continue with next batch despite error

        # Mark session complete
        db.refresh(session)
        session.status = "completed"
        session.computed_pairs = total_computed
        session.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            "batch_matching_completed",
            session_id=session_id,
            total_computed=total_computed,
        )
