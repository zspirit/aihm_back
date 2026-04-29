import uuid

import pytest
import pytest_asyncio

from app.models.candidate import Candidate
from app.models.position import Position

from tests.conftest import _create_user, TestSession


@pytest_asyncio.fixture()
async def pipeline_data(_setup_db):
    """Create tenant + user + position + candidates in various pipeline statuses."""
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "pipeline@test.com", "admin")

        position = Position(
            tenant_id=tenant.id,
            title="Dev Python",
            description="Backend developer",
            required_skills=["python"],
            custom_questions=[],
            created_by=user.id,
        )
        session.add(position)
        await session.flush()

        candidates = []
        for i, status in enumerate(["new", "new", "cv_scored", "interview_completed", "hired"]):
            c = Candidate(
                tenant_id=tenant.id,
                name=f"Candidate {i}",
                email=f"c{i}@test.com",
                position_id=position.id,
                pipeline_status=status,
                cv_score=50.0 + i * 10,
            )
            session.add(c)
            candidates.append(c)

        await session.commit()

        return {
            "headers": headers,
            "user": user,
            "tenant": tenant,
            "position": position,
            "candidates": candidates,
        }


@pytest.mark.asyncio
async def test_pipeline_board(client, pipeline_data):
    resp = await client.get(
        "/api/v1/pipeline/board",
        headers=pipeline_data["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "columns" in data
    assert len(data["columns"]) == 9  # all pipeline statuses

    # Check the 'new' column has 2 candidates
    new_col = next(c for c in data["columns"] if c["status"] == "new")
    assert new_col["count"] == 2
    assert len(new_col["candidates"]) == 2

    # Check hired column
    hired_col = next(c for c in data["columns"] if c["status"] == "hired")
    assert hired_col["count"] == 1


@pytest.mark.asyncio
async def test_pipeline_board_filter_by_position(client, pipeline_data):
    position_id = str(pipeline_data["position"].id)
    resp = await client.get(
        f"/api/v1/pipeline/board?position_id={position_id}",
        headers=pipeline_data["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    total = sum(c["count"] for c in data["columns"])
    assert total == 5


@pytest.mark.asyncio
async def test_pipeline_board_no_auth(client):
    resp = await client.get("/api/v1/pipeline/board")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_pipeline_move(client, pipeline_data):
    candidate = pipeline_data["candidates"][0]  # status=new
    resp = await client.patch(
        "/api/v1/pipeline/move",
        headers=pipeline_data["headers"],
        json={
            "candidate_id": str(candidate.id),
            "new_status": "cv_scored",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pipeline_status"] == "cv_scored"
    assert data["previous_status"] == "new"


@pytest.mark.asyncio
async def test_pipeline_move_invalid_status(client, pipeline_data):
    candidate = pipeline_data["candidates"][0]
    resp = await client.patch(
        "/api/v1/pipeline/move",
        headers=pipeline_data["headers"],
        json={
            "candidate_id": str(candidate.id),
            "new_status": "invalid_status",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_pipeline_move_same_status(client, pipeline_data):
    candidate = pipeline_data["candidates"][0]  # status=new
    resp = await client.patch(
        "/api/v1/pipeline/move",
        headers=pipeline_data["headers"],
        json={
            "candidate_id": str(candidate.id),
            "new_status": "new",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_pipeline_move_not_found(client, pipeline_data):
    resp = await client.patch(
        "/api/v1/pipeline/move",
        headers=pipeline_data["headers"],
        json={
            "candidate_id": str(uuid.uuid4()),
            "new_status": "cv_scored",
        },
    )
    assert resp.status_code == 404
