"""Matching worker — batch N*M matching via Celery."""

import structlog
from celery import shared_task

logger = structlog.get_logger()


@shared_task(name="matching.compute_matrix", bind=True, max_retries=2)
def compute_match_matrix(self, session_id: str):
    """
    Compute all N*M match scores for a MatchSession.
    Loads positions and candidates, calls Claude API in batches, upserts results.
    """
    try:
        from app.services.batch_matching import compute_batch_matching
        compute_batch_matching(session_id)
        logger.info("compute_match_matrix_done", session_id=session_id)
    except Exception as exc:
        logger.error("compute_match_matrix_error", session_id=session_id, error=str(exc))
        raise self.retry(exc=exc, countdown=30)


@shared_task(name="matching.score", bind=True, max_retries=2)
def score_matches(self, position_data: dict, candidate_dicts: list, tenant_id: str):
    """Legacy placeholder — kept for backwards compatibility."""
    pass
