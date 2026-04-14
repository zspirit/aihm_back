"""Automatic purge of expired candidate data based on tenant retention policy."""
from datetime import datetime, timezone, timedelta

import structlog
from celery import shared_task

from app.workers.base import get_sync_session

logger = structlog.get_logger()


@shared_task(name="purge.expired_data")
def purge_expired_data():
    """Anonymize candidates exceeding retention days (per tenant)."""
    session = get_sync_session()
    try:
        from app.models.tenant import Tenant
        from app.models.candidate import Candidate
        from app.services.cv_anonymizer import anonymize_candidate_data

        tenants = session.query(Tenant).all()
        total_purged = 0

        for tenant in tenants:
            retention_days = tenant.data_retention_days or 180
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

            candidates = session.query(Candidate).filter(
                Candidate.tenant_id == tenant.id,
                Candidate.is_anonymized.is_(False),
                Candidate.created_at < cutoff,
            ).all()

            for candidate in candidates:
                anonymized = anonymize_candidate_data(str(candidate.id), candidate.cv_parsed_data)
                candidate.name = anonymized.get("anonymous_id", "Anonyme")
                candidate.email = None
                candidate.phone = None
                candidate.cv_parsed_data = anonymized
                candidate.cv_file_path = None
                candidate.summary_json = None
                candidate.feedback_json = None
                candidate.is_anonymized = True

            if candidates:
                session.commit()
                total_purged += len(candidates)
                logger.info(
                    "purge_tenant_done",
                    tenant_id=str(tenant.id),
                    tenant_name=tenant.name,
                    purged_count=len(candidates),
                    retention_days=retention_days,
                )

        logger.info("purge_expired_data_done", total_purged=total_purged)
    except Exception as e:
        session.rollback()
        logger.error("purge_expired_data_error", error=str(e))
        raise
    finally:
        session.close()
