"""Tests for notification_service — create_notification edge cases."""
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

from app.services.notification_service import create_notification


def _mock_db(users=None):
    """Create a mock DB session that returns given users for admin/recruiter query."""
    db = MagicMock()
    if users is not None:
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = users
        db.execute.return_value = mock_result
    return db


class TestCreateNotificationSingleUser:
    def test_creates_notification_for_specific_user(self):
        db = MagicMock()
        tid = uuid4()
        uid = uuid4()

        create_notification(db, tid, uid, "info", "Title", "Message")

        db.add.assert_called_once()
        notif = db.add.call_args[0][0]
        assert notif.tenant_id == tid
        assert notif.user_id == uid
        assert notif.type == "info"
        assert notif.title == "Title"
        assert notif.message == "Message"
        db.flush.assert_called_once()

    def test_creates_notification_with_data(self):
        db = MagicMock()
        data = {"candidate_id": "abc", "score": 85}

        create_notification(db, uuid4(), uuid4(), "score", "Score", "msg", data=data)

        notif = db.add.call_args[0][0]
        assert notif.data == data

    def test_creates_notification_without_data(self):
        db = MagicMock()

        create_notification(db, uuid4(), uuid4(), "info", "T", "M")

        notif = db.add.call_args[0][0]
        assert notif.data is None


class TestCreateNotificationBulk:
    def test_notifies_all_admins_and_recruiters(self):
        user1 = MagicMock(id=uuid4())
        user2 = MagicMock(id=uuid4())
        user3 = MagicMock(id=uuid4())
        db = _mock_db(users=[user1, user2, user3])
        tid = uuid4()

        create_notification(db, tid, None, "alert", "Alert", "Something happened")

        assert db.add.call_count == 3
        db.flush.assert_called_once()

    def test_no_admins_found_creates_nothing(self):
        db = _mock_db(users=[])
        tid = uuid4()

        create_notification(db, tid, None, "alert", "Alert", "msg")

        db.add.assert_not_called()
        db.flush.assert_called_once()

    def test_bulk_notification_preserves_data(self):
        user1 = MagicMock(id=uuid4())
        db = _mock_db(users=[user1])
        data = {"key": "value"}

        create_notification(db, uuid4(), None, "info", "T", "M", data=data)

        notif = db.add.call_args[0][0]
        assert notif.data == data
