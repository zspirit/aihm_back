"""Tests for audit logging service."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.audit import log_action


@pytest.mark.asyncio
async def test_log_action_creates_entry():
    db = AsyncMock()
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    with patch("app.services.audit.AuditLog") as MockLog:
        instance = MagicMock()
        MockLog.return_value = instance
        await log_action(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="cv.uploaded",
            entity_type="candidate",
            entity_id="abc-123",
            details={"filename": "cv.pdf"},
        )
        MockLog.assert_called_once_with(
            tenant_id=tenant_id,
            user_id=user_id,
            action="cv.uploaded",
            entity_type="candidate",
            entity_id="abc-123",
            details={"filename": "cv.pdf"},
        )
        db.add.assert_called_once_with(instance)


@pytest.mark.asyncio
async def test_log_action_swallows_exceptions():
    """log_action should never raise, even on DB error."""
    db = AsyncMock()
    db.add.side_effect = RuntimeError("DB gone")

    with patch("app.services.audit.AuditLog", return_value=MagicMock()):
        # Should NOT raise
        await log_action(
            db,
            tenant_id=uuid.uuid4(),
            action="test",
            entity_type="test",
        )


@pytest.mark.asyncio
async def test_log_action_optional_fields():
    db = AsyncMock()
    with patch("app.services.audit.AuditLog") as MockLog:
        MockLog.return_value = MagicMock()
        await log_action(
            db,
            tenant_id=uuid.uuid4(),
            action="login",
            entity_type="user",
        )
        call_kwargs = MockLog.call_args[1]
        assert call_kwargs["user_id"] is None
        assert call_kwargs["entity_id"] is None
        assert call_kwargs["details"] is None
