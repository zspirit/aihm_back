"""Tests for skills API endpoints."""
import pytest


@pytest.mark.asyncio
async def test_search_skills_empty(client, auth_headers):
    """Test searching skills when none exist."""
    response = await client.get("/skills/search?query=python", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_skills_missing_query(client, auth_headers):
    """Test search without query parameter."""
    response = await client.get("/skills/search", headers=auth_headers)
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_search_skills_limit(client, auth_headers):
    """Test search with limit parameter."""
    response = await client.get("/skills/search?query=python&limit=5", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_similar_skills_not_found(client, auth_headers):
    """Test getting similar skills for non-existent skill."""
    non_existent_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/skills/similar/{non_existent_id}", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_trending_skills(client, auth_headers):
    """Test getting trending skills."""
    response = await client.get("/skills/trending", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_trending_skills_with_params(client, auth_headers):
    """Test trending skills with limit and days parameters."""
    response = await client.get("/skills/trending?limit=10&days=30", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) <= 10


@pytest.mark.asyncio
async def test_skills_unauthenticated(client):
    """Test that unauthenticated requests are rejected."""
    response = await client.get("/skills/search?query=python")
    assert response.status_code == 401
