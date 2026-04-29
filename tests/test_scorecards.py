"""Tests for collaborative scorecard system (4.7)."""
import uuid

import pytest
import pytest_asyncio

from tests.conftest import _create_user, TestSession


async def _create_interview(db_session, tenant_id, user_id):
    """Helper: create a position, candidate, and interview for scorecard tests."""
    from app.models.position import Position
    from app.models.candidate import Candidate
    from app.models.interview import Interview

    position = Position(
        tenant_id=tenant_id,
        title="Dev Python",
        required_skills=["Python"],
        created_by=user_id,
    )
    db_session.add(position)
    await db_session.flush()

    candidate = Candidate(
        position_id=position.id,
        tenant_id=tenant_id,
        name="Test Candidat",
    )
    db_session.add(candidate)
    await db_session.flush()

    interview = Interview(
        candidate_id=candidate.id,
        position_id=position.id,
        tenant_id=tenant_id,
        status="completed",
    )
    db_session.add(interview)
    await db_session.commit()

    return str(interview.id)


@pytest_asyncio.fixture()
async def interview_with_auth(db_session):
    """Create a user, tenant, and interview. Returns (auth_headers, interview_id, user, tenant)."""
    headers, user, tenant = await _create_user(db_session, "recruiter@test.com", "recruiter")
    interview_id = await _create_interview(db_session, tenant.id, user.id)
    return headers, interview_id, user, tenant


class TestScorecardCreate:
    """POST /api/v1/interviews/{id}/scorecard"""

    @pytest.mark.asyncio
    async def test_create_scorecard_201(self, client, interview_with_auth):
        headers, interview_id, _, _ = interview_with_auth
        payload = {
            "technical": 4,
            "problem_solving": 5,
            "communication": 3,
            "behavioral": 4,
            "notes": "Bon candidat technique",
        }

        res = await client.post(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
            json=payload,
        )
        assert res.status_code == 201
        data = res.json()
        assert data["technical"] == 4
        assert data["problem_solving"] == 5
        assert data["communication"] == 3
        assert data["behavioral"] == 4
        assert data["notes"] == "Bon candidat technique"
        assert "id" in data
        assert "evaluator_id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_update_scorecard_returns_201_on_upsert(self, client, interview_with_auth):
        """Updating existing scorecard via upsert still returns the updated data."""
        headers, interview_id, _, _ = interview_with_auth

        # First create
        await client.post(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
            json={"technical": 3, "problem_solving": 3, "communication": 3, "behavioral": 3},
        )

        # Update (upsert)
        res = await client.post(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
            json={"technical": 5, "problem_solving": 4, "communication": 5, "behavioral": 4, "notes": "Revise"},
        )
        # The endpoint returns 201 always (upsert behavior)
        assert res.status_code == 201
        data = res.json()
        assert data["technical"] == 5
        assert data["problem_solving"] == 4
        assert data["notes"] == "Revise"

    @pytest.mark.asyncio
    async def test_scorecard_validation_below_range(self, client, interview_with_auth):
        """Score below 1 should return 422."""
        headers, interview_id, _, _ = interview_with_auth
        payload = {"technical": 0, "problem_solving": 3, "communication": 3, "behavioral": 3}

        res = await client.post(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
            json=payload,
        )
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_scorecard_validation_above_range(self, client, interview_with_auth):
        """Score above 5 should return 422."""
        headers, interview_id, _, _ = interview_with_auth
        payload = {"technical": 3, "problem_solving": 6, "communication": 3, "behavioral": 3}

        res = await client.post(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
            json=payload,
        )
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_scorecard_nonexistent_interview_404(self, client, interview_with_auth):
        """Scorecard for non-existent interview returns 404."""
        headers, _, _, _ = interview_with_auth
        fake_id = str(uuid.uuid4())

        res = await client.post(
            f"/api/v1/interviews/{fake_id}/scorecard",
            headers=headers,
            json={"technical": 3, "problem_solving": 3, "communication": 3, "behavioral": 3},
        )
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_scorecard_without_notes(self, client, interview_with_auth):
        """Scorecard without notes should work (notes is optional)."""
        headers, interview_id, _, _ = interview_with_auth
        payload = {"technical": 4, "problem_solving": 4, "communication": 4, "behavioral": 4}

        res = await client.post(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
            json=payload,
        )
        assert res.status_code == 201
        assert res.json()["notes"] is None


class TestScorecardGet:
    """GET /api/v1/interviews/{id}/scorecard"""

    @pytest.mark.asyncio
    async def test_get_scorecards_empty(self, client, interview_with_auth):
        """No scorecards returns empty list with zero aggregates."""
        headers, interview_id, _, _ = interview_with_auth

        res = await client.get(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["scorecards"] == []
        assert data["aggregated"]["total_evaluators"] == 0
        assert data["aggregated"]["technical_avg"] == 0.0

    @pytest.mark.asyncio
    async def test_get_scorecards_single_evaluator(self, client, interview_with_auth):
        """Single evaluator: aggregate equals individual scores."""
        headers, interview_id, _, _ = interview_with_auth

        await client.post(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
            json={"technical": 4, "problem_solving": 5, "communication": 3, "behavioral": 4},
        )

        res = await client.get(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data["scorecards"]) == 1
        agg = data["aggregated"]
        assert agg["total_evaluators"] == 1
        assert agg["technical_avg"] == 4.0
        assert agg["problem_solving_avg"] == 5.0
        assert agg["communication_avg"] == 3.0
        assert agg["behavioral_avg"] == 4.0

    @pytest.mark.asyncio
    async def test_get_scorecards_nonexistent_interview_404(self, client, interview_with_auth):
        """GET scorecard for non-existent interview returns 404."""
        headers, _, _, _ = interview_with_auth
        fake_id = str(uuid.uuid4())

        res = await client.get(
            f"/api/v1/interviews/{fake_id}/scorecard",
            headers=headers,
        )
        assert res.status_code == 404


class TestScorecardAggregate:
    """Test aggregate calculation with multiple evaluators."""

    @pytest.mark.asyncio
    async def test_aggregate_three_evaluators(self, client, db_session, interview_with_auth):
        """Three evaluators: verify average calculated correctly."""
        headers1, interview_id, user1, tenant = interview_with_auth

        # Create 2 more users in the SAME tenant directly
        from app.core.security import hash_password
        from app.models.user import User
        from app.models.scorecard import Scorecard

        user2 = User(
            tenant_id=tenant.id,
            email="eval2@test.com",
            password_hash=hash_password("testpass123"),
            full_name="Evaluator 2",
            role="recruiter",
        )
        user3 = User(
            tenant_id=tenant.id,
            email="eval3@test.com",
            password_hash=hash_password("testpass123"),
            full_name="Evaluator 3",
            role="admin",
        )
        db_session.add_all([user2, user3])
        await db_session.flush()

        scores = [
            (user1.id, 5, 4, 3, 4),
            (user2.id, 3, 5, 4, 2),
            (user3.id, 4, 3, 5, 3),
        ]
        for uid, tech, ps, comm, beh in scores:
            sc = Scorecard(
                interview_id=interview_id,
                tenant_id=tenant.id,
                evaluator_id=uid,
                technical=tech,
                problem_solving=ps,
                communication=comm,
                behavioral=beh,
            )
            db_session.add(sc)
        await db_session.commit()

        res = await client.get(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers1,
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data["scorecards"]) == 3
        agg = data["aggregated"]
        assert agg["total_evaluators"] == 3
        # Averages: tech=(5+3+4)/3=4.0, ps=(4+5+3)/3=4.0, comm=(3+4+5)/3=4.0, beh=(4+2+3)/3=3.0
        assert agg["technical_avg"] == 4.0
        assert agg["problem_solving_avg"] == 4.0
        assert agg["communication_avg"] == 4.0
        assert agg["behavioral_avg"] == 3.0


class TestScorecardSchema:
    """Test schema validation edge cases."""

    @pytest.mark.asyncio
    async def test_scorecard_boundary_min(self, client, interview_with_auth):
        """Score of 1 (minimum) should be accepted."""
        headers, interview_id, _, _ = interview_with_auth
        payload = {"technical": 1, "problem_solving": 1, "communication": 1, "behavioral": 1}

        res = await client.post(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
            json=payload,
        )
        assert res.status_code == 201

    @pytest.mark.asyncio
    async def test_scorecard_boundary_max(self, client, interview_with_auth):
        """Score of 5 (maximum) should be accepted."""
        headers, interview_id, _, _ = interview_with_auth
        payload = {"technical": 5, "problem_solving": 5, "communication": 5, "behavioral": 5}

        res = await client.post(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
            json=payload,
        )
        assert res.status_code == 201

    @pytest.mark.asyncio
    async def test_scorecard_missing_field_422(self, client, interview_with_auth):
        """Missing required field returns 422."""
        headers, interview_id, _, _ = interview_with_auth
        payload = {"technical": 3, "problem_solving": 3}  # missing communication, behavioral

        res = await client.post(
            f"/api/v1/interviews/{interview_id}/scorecard",
            headers=headers,
            json=payload,
        )
        assert res.status_code == 422
