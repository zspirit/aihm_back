"""Matching worker — placeholder for future async matching tasks."""

from celery import shared_task


@shared_task(name="matching.score", bind=True, max_retries=2)
def score_matches(self, position_data: dict, candidate_dicts: list, tenant_id: str):
    """Run AI scoring on pre-filtered candidates.

    Currently matching is done synchronously in the endpoint.
    This task is reserved for future heavy matching workloads.
    """
    pass
