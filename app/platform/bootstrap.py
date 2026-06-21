"""Module registry bootstrap.

Importing a module package wires its event handlers (subscribe-on-import).
Call :func:`register_modules` once at app startup (and from tests).
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

_registered = False


def register_modules() -> None:
    global _registered
    if _registered:
        return
    # Importing each module package triggers its handler subscriptions.
    from app.modules import timesheet  # noqa: F401

    _registered = True
    logger.info("platform_modules_registered", modules=["timesheet"])
