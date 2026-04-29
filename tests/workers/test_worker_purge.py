"""Tests for purge worker — all external deps mocked."""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest


def _make_tenant(retention_days=180):
    t = MagicMock()
    t.id = uuid.uuid4()
    t.name = "Acme"
    t.data_retention_days = retention_days
    return t


def _make_candidate(tenant_id, days_old=200, anonymized=False):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.tenant_id = tenant_id
    c.name = "Alice"
    c.email = "a@t.com"
    c.phone = "+33600000000"
    c.cv_parsed_data = {"skills": ["Python"]}
    c.cv_file_path = "cvs/test.pdf"
    c.summary_json = {"pitch": "dev"}
    c.feedback_json = None
    c.is_anonymized = anonymized
    c.created_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    return c


def test_purge_anonymizes_expired_candidates():
    tenant = _make_tenant(retention_days=90)
    old_cand = _make_candidate(tenant.id, days_old=100)
    recent_cand = _make_candidate(tenant.id, days_old=10)

    sess = MagicMock()

    # Setup query side effects: first call returns Tenants, second returns Candidates
    def _query_side_effect(model):
        q = MagicMock()
        if model.__name__ == "Tenant":
            q.all.return_value = [tenant]
        else:
            q.filter.return_value.all.return_value = [old_cand]
        return q

    sess.query.side_effect = _query_side_effect

    with patch("app.workers.purge.get_sync_session", return_value=sess), \
         patch("app.services.cv_anonymizer.anonymize_candidate_data", return_value={"anonymous_id": "Candidat #ABCD"}) as mock_anon:
        from app.workers.purge import purge_expired_data
        purge_expired_data()

    assert old_cand.is_anonymized is True
    assert old_cand.email is None
    assert old_cand.phone is None
    assert old_cand.cv_file_path is None


def test_purge_skips_already_anonymized():
    tenant = _make_tenant(retention_days=90)

    sess = MagicMock()

    def _query_side_effect(model):
        q = MagicMock()
        if model.__name__ == "Tenant":
            q.all.return_value = [tenant]
        else:
            q.filter.return_value.all.return_value = []  # No candidates match
        return q

    sess.query.side_effect = _query_side_effect

    with patch("app.workers.purge.get_sync_session", return_value=sess):
        from app.workers.purge import purge_expired_data
        purge_expired_data()

    # commit should not be called when no candidates are purged
    sess.commit.assert_not_called()
