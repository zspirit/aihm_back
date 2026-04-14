"""Tests for metrics API endpoints."""
import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_get_position_metrics_not_found(client, auth_headers):
    """Test getting metrics for non-existent position."""
    non_existent_id = str(uuid4())
    response = await client.get(f"/metrics/positions/{non_existent_id}", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_enterprise_metrics_not_found(client, auth_headers):
    """Test getting metrics for non-existent enterprise."""
    non_existent_id = str(uuid4())
    response = await client.get(f"/metrics/enterprises/{non_existent_id}", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_analytics_overview(client, auth_headers):
    """Test getting analytics overview."""
    response = await client.get("/metrics/analytics/overview", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "period_days" in data
    assert "total_positions" in data
    assert "total_candidates" in data
    assert "recent_applications" in data
    assert "recent_interviews" in data
    assert "recent_offers" in data
    assert "recent_hired" in data


@pytest.mark.asyncio
async def test_get_analytics_overview_with_days(client, auth_headers):
    """Test analytics overview with custom days parameter."""
    response = await client.get("/metrics/analytics/overview?days=90", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["period_days"] == 90


@pytest.mark.asyncio
async def test_get_analytics_overview_invalid_days(client, auth_headers):
    """Test analytics overview with invalid days parameter."""
    response = await client.get("/metrics/analytics/overview?days=400", headers=auth_headers)
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_metrics_unauthenticated(client):
    """Test that unauthenticated requests are rejected."""
    response = await client.get("/metrics/analytics/overview")
    assert response.status_code == 401
