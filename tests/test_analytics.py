import pytest


@pytest.mark.asyncio
async def test_analytics_overview(client, admin_data):
    headers, user, tenant = admin_data
    res = await client.get("/api/v1/analytics/overview", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "total_positions" in data
    assert "total_candidates" in data
    assert "total_interviews" in data
    assert "completed_interviews" in data
    assert "success_rate" in data
    assert "avg_cv_score" in data
    assert "avg_interview_duration_s" in data
    # Empty tenant → all zeros
    assert data["total_positions"] == 0
    assert data["total_candidates"] == 0


@pytest.mark.asyncio
async def test_analytics_overview_no_auth(client):
    res = await client.get("/api/v1/analytics/overview")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_analytics_pipeline(client, admin_data):
    headers, *_ = admin_data
    res = await client.get("/api/v1/analytics/pipeline", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_analytics_positions_stats(client, admin_data):
    headers, *_ = admin_data
    res = await client.get("/api/v1/analytics/positions-stats", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_analytics_with_position(client, admin_data):
    """After creating a position, overview should reflect it."""
    headers, *_ = admin_data
    # Create a position
    await client.post(
        "/api/v1/positions",
        headers=headers,
        json={"title": "Dev Python", "description": "Backend dev"},
    )
    res = await client.get("/api/v1/analytics/overview", headers=headers)
    assert res.status_code == 200
    assert res.json()["total_positions"] == 1

    # positions-stats should include it
    res = await client.get("/api/v1/analytics/positions-stats", headers=headers)
    assert res.status_code == 200
    stats = res.json()
    assert len(stats) == 1
    assert stats[0]["title"] == "Dev Python"
