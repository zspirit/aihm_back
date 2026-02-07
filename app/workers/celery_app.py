from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "aihm",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.autodiscover_tasks([
    "app.workers.cv_processing",
    "app.workers.question_generation",
    "app.workers.telephony",
    "app.workers.transcription",
    "app.workers.analysis",
    "app.workers.report_generation",
    "app.workers.notifications",
])
