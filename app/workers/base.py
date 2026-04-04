"""Shared utilities for Celery workers — DB session lifecycle + error handling."""

from contextlib import contextmanager

import structlog

logger = structlog.get_logger()


def get_sync_session():
    from app.core.database import sync_session_factory

    return sync_session_factory()


@contextmanager
def worker_session():
    """Context manager for DB session with auto-rollback on error and auto-close."""
    session = get_sync_session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def worker_task(task_name: str, self, retry_countdown: int = 30, **log_kwargs):
    """Decorator-style helper. Returns a context manager that handles the full
    worker lifecycle: session, logging, error handling, retry.

    Usage:
        with worker_task("analysis", self, interview_id=interview_id) as ctx:
            session = ctx.session
            # ... do work ...

    On exception: rollback, log error, retry via self.retry().
    """
    return _WorkerTaskContext(task_name, self, retry_countdown, log_kwargs)


class _WorkerTaskContext:
    __slots__ = ("task_name", "celery_task", "retry_countdown", "log_kwargs", "session")

    def __init__(self, task_name, celery_task, retry_countdown, log_kwargs):
        self.task_name = task_name
        self.celery_task = celery_task
        self.retry_countdown = retry_countdown
        self.log_kwargs = log_kwargs
        self.session = None

    def __enter__(self):
        logger.info(f"{self.task_name}_start", **self.log_kwargs)
        self.session = get_sync_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.session.rollback()
            logger.error(f"{self.task_name}_error", error=str(exc_val), **self.log_kwargs)
            self.session.close()
            raise self.celery_task.retry(exc=exc_val, countdown=self.retry_countdown)
        self.session.close()
        return False
