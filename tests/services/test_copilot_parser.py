"""Tests for copilot_parser service (DB query handlers)."""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

import pytest
import pytest_asyncio

from app.services.copilot_parser import (
    handle_search_candidates,
    handle_list_positions,
    handle_get_position_details,
    handle_get_candidate_details,
    handle_get_analytics_overview,
    handle_aggregate_scores,
    handle_get_pipeline_breakdown,
)


def _make_candidate(**overrides):
    now = datetime.now(timezone.utc)
    c = MagicMock()
    c.id = overrides.get("id", uuid4())
    c.name = overrides.get("name", "Jean Dupont")
    c.email = overrides.get("email", "jean@test.com")
    c.phone = overrides.get("phone", "+33600000000")
    c.position_id = overrides.get("position_id", uuid4())
    c.cv_score = overrides.get("cv_score", 75.0)
    c.cv_score_explanation = overrides.get("cv_score_explanation", "Bon profil")
    c.cv_parsed_data = overrides.get("cv_parsed_data", {"skills": ["Python"]})
    c.pipeline_status = overrides.get("pipeline_status", "scored")
    c.created_at = overrides.get("created_at", now)
    c.tenant_id = overrides.get("tenant_id", uuid4())
    return c


def _make_position(**overrides):
    now = datetime.now(timezone.utc)
    p = MagicMock()
    p.id = overrides.get("id", uuid4())
    p.title = overrides.get("title", "Backend Dev")
    p.description = overrides.get("description", "Python backend role")
    p.required_skills = overrides.get("required_skills", ["Python", "SQL"])
    p.seniority_level = overrides.get("seniority_level", "mid")
    p.status = overrides.get("status", "active")
    p.created_at = overrides.get("created_at", now)
    p.tenant_id = overrides.get("tenant_id", uuid4())
    return p


def _mock_db_result(items):
    """Create a mock db result that supports .scalars().all()"""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result.scalars.return_value = scalars_mock
    result.scalar_one_or_none.return_value = items[0] if items else None
    result.scalar.return_value = len(items)
    return result


@pytest.fixture
def db():
    mock = AsyncMock()
    return mock


@pytest.fixture
def tenant_id():
    return uuid4()


class TestHandleSearchCandidates:
    @pytest.mark.asyncio
    async def test_returns_candidates(self, db, tenant_id):
        c = _make_candidate()
        db.execute.return_value = _mock_db_result([c])

        result = await handle_search_candidates(db, tenant_id, {})
        data = json.loads(result)

        assert data["total"] == 1
        assert data["candidates"][0]["name"] == "Jean Dupont"

    @pytest.mark.asyncio
    async def test_empty_results(self, db, tenant_id):
        db.execute.return_value = _mock_db_result([])

        result = await handle_search_candidates(db, tenant_id, {})
        data = json.loads(result)
        assert data["total"] == 0
        assert data["candidates"] == []

    @pytest.mark.asyncio
    async def test_with_filters(self, db, tenant_id):
        c = _make_candidate()
        db.execute.return_value = _mock_db_result([c])

        params = {
            "position_id": str(uuid4()),
            "min_score": 50,
            "max_score": 90,
            "status": "scored",
            "search": "jean",
            "limit": 10,
        }
        result = await handle_search_candidates(db, tenant_id, params)
        data = json.loads(result)
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_invalid_position_id_ignored(self, db, tenant_id):
        db.execute.return_value = _mock_db_result([])
        result = await handle_search_candidates(db, tenant_id, {"position_id": "not-a-uuid"})
        data = json.loads(result)
        assert data["total"] == 0


class TestHandleListPositions:
    @pytest.mark.asyncio
    async def test_returns_positions(self, db, tenant_id):
        p = _make_position()
        db.execute.return_value = _mock_db_result([p])

        result = await handle_list_positions(db, tenant_id, {})
        data = json.loads(result)
        assert data["total"] == 1
        assert data["positions"][0]["title"] == "Backend Dev"

    @pytest.mark.asyncio
    async def test_with_filters(self, db, tenant_id):
        p = _make_position()
        db.execute.return_value = _mock_db_result([p])

        result = await handle_list_positions(db, tenant_id, {"status": "active", "search": "back"})
        data = json.loads(result)
        assert data["total"] == 1


class TestHandleGetPositionDetails:
    @pytest.mark.asyncio
    async def test_found(self, db, tenant_id):
        p = _make_position()
        # First call: position query, second call: count query
        result_pos = MagicMock()
        result_pos.scalar_one_or_none.return_value = p
        result_count = MagicMock()
        result_count.scalar.return_value = 5
        db.execute.side_effect = [result_pos, result_count]

        result = await handle_get_position_details(db, tenant_id, {"position_id": str(uuid4())})
        data = json.loads(result)
        assert data["title"] == "Backend Dev"
        assert data["candidate_count"] == 5

    @pytest.mark.asyncio
    async def test_not_found(self, db, tenant_id):
        result_pos = MagicMock()
        result_pos.scalar_one_or_none.return_value = None
        db.execute.return_value = result_pos

        result = await handle_get_position_details(db, tenant_id, {"position_id": str(uuid4())})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_invalid_id(self, db, tenant_id):
        result = await handle_get_position_details(db, tenant_id, {"position_id": "bad"})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_missing_id(self, db, tenant_id):
        result = await handle_get_position_details(db, tenant_id, {})
        data = json.loads(result)
        assert "error" in data


class TestHandleGetAnalyticsOverview:
    @pytest.mark.asyncio
    async def test_returns_analytics(self, db, tenant_id):
        # 5 sequential db.execute calls
        results = []
        for val in [10, 3, 72.5, 7, 2]:
            r = MagicMock()
            r.scalar.return_value = val
            results.append(r)
        db.execute.side_effect = results

        result = await handle_get_analytics_overview(db, tenant_id, {})
        data = json.loads(result)

        assert data["total_candidates"] == 10
        assert data["active_positions"] == 3
        assert data["avg_cv_score"] == 72.5
        assert data["completed_interviews"] == 7
        assert data["consent_given"] == 2
        assert data["conversion_rate_percent"] == 70.0


class TestHandleGetPipelineBreakdown:
    @pytest.mark.asyncio
    async def test_returns_breakdown(self, db, tenant_id):
        row1 = MagicMock()
        row1.pipeline_status = "scored"
        row1.count = 5
        row2 = MagicMock()
        row2.pipeline_status = "consent_given"
        row2.count = 3

        result_mock = MagicMock()
        result_mock.fetchall.return_value = [row1, row2]
        db.execute.return_value = result_mock

        result = await handle_get_pipeline_breakdown(db, tenant_id, {})
        data = json.loads(result)

        assert data["total"] == 8
        assert data["breakdown"]["scored"] == 5
        assert data["breakdown"]["consent_given"] == 3


class TestHandleAggregateScores:
    @pytest.mark.asyncio
    async def test_cv_score_aggregation(self, db, tenant_id):
        row = MagicMock()
        row.avg = 72.5
        row.min = 45.0
        row.max = 95.0
        row.count = 10
        result_mock = MagicMock()
        result_mock.one.return_value = row
        db.execute.return_value = result_mock

        result = await handle_aggregate_scores(db, tenant_id, {"score_type": "cv_score"})
        data = json.loads(result)

        assert data["average"] == 72.5
        assert data["min"] == 45.0
        assert data["max"] == 95.0
        assert data["count"] == 10

    @pytest.mark.asyncio
    async def test_interview_score_aggregation(self, db, tenant_id):
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            ({"technical": 80, "communication": 60},),
            ({"technical": 70, "communication": 50},),
        ]
        db.execute.return_value = result_mock

        result = await handle_aggregate_scores(db, tenant_id, {"score_type": "technical"})
        data = json.loads(result)

        assert data["average"] == 75.0
        assert data["min"] == 70.0
        assert data["max"] == 80.0
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_no_data(self, db, tenant_id):
        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        db.execute.return_value = result_mock

        result = await handle_aggregate_scores(db, tenant_id, {"score_type": "technical"})
        data = json.loads(result)

        assert data["count"] == 0
        assert data["average"] is None
