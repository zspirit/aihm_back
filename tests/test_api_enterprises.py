import pytest
from httpx import AsyncClient
import json


@pytest.mark.asyncio
async def test_list_enterprises_empty(client, auth_headers):
    """Test listing enterprises when none exist."""
    response = await client.get("/enterprises", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_enterprise(client, auth_headers):
    """Test creating an enterprise."""
    payload = {
        "name": "Acme Corp",
        "industry": "Technology",
        "domain": "acme.com",
        "contact_email": "contact@acme.com",
        "contact_phone": "+1234567890",
        "address": "123 Tech Street",
    }
    response = await client.post("/enterprises", json=payload, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Acme Corp"
    assert data["industry"] == "Technology"
    assert data["status"] == "active"
    assert "id" in data
    assert "tenant_id" in data
    return data["id"]


@pytest.mark.asyncio
async def test_create_enterprise_minimal(client, auth_headers):
    """Test creating an enterprise with minimal fields."""
    payload = {"name": "Minimal Corp"}
    response = await client.post("/enterprises", json=payload, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Minimal Corp"
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_create_enterprise_missing_name(client, auth_headers):
    """Test creating an enterprise without name fails."""
    payload = {"industry": "Tech"}
    response = await client.post("/enterprises", json=payload, headers=auth_headers)
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_list_enterprises_after_create(client, auth_headers):
    """Test listing enterprises after creating some."""
    # Create 2 enterprises
    for i in range(2):
        payload = {"name": f"Company {i+1}"}
        await client.post("/enterprises", json=payload, headers=auth_headers)

    # List
    response = await client.get("/enterprises", headers=auth_headers)
    assert response.status_code == 200
    enterprises = response.json()
    assert len(enterprises) == 2


@pytest.mark.asyncio
async def test_get_enterprise(client, auth_headers):
    """Test getting a specific enterprise."""
    # Create
    create_payload = {"name": "Test Company", "industry": "Retail"}
    create_response = await client.post("/enterprises", json=create_payload, headers=auth_headers)
    enterprise_id = create_response.json()["id"]

    # Get
    response = await client.get(f"/enterprises/{enterprise_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == enterprise_id
    assert data["name"] == "Test Company"
    assert data["industry"] == "Retail"


@pytest.mark.asyncio
async def test_get_nonexistent_enterprise(client, auth_headers):
    """Test getting a nonexistent enterprise."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/enterprises/{fake_id}", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_enterprise(client, auth_headers):
    """Test updating an enterprise."""
    # Create
    create_payload = {"name": "Old Name", "industry": "Tech"}
    create_response = await client.post("/enterprises", json=create_payload, headers=auth_headers)
    enterprise_id = create_response.json()["id"]

    # Update
    update_payload = {"name": "New Name", "industry": "Finance"}
    response = await client.put(
        f"/enterprises/{enterprise_id}",
        json=update_payload,
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Name"
    assert data["industry"] == "Finance"


@pytest.mark.asyncio
async def test_update_enterprise_partial(client, auth_headers):
    """Test partial update (only name)."""
    # Create
    create_payload = {"name": "Original", "industry": "Tech", "domain": "original.com"}
    create_response = await client.post("/enterprises", json=create_payload, headers=auth_headers)
    enterprise_id = create_response.json()["id"]

    # Partial update
    update_payload = {"name": "Updated Name"}
    response = await client.put(
        f"/enterprises/{enterprise_id}",
        json=update_payload,
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["industry"] == "Tech"  # unchanged
    assert data["domain"] == "original.com"  # unchanged


@pytest.mark.asyncio
async def test_delete_enterprise(client, auth_headers):
    """Test deleting (archiving) an enterprise."""
    # Create
    create_payload = {"name": "To Archive"}
    create_response = await client.post("/enterprises", json=create_payload, headers=auth_headers)
    enterprise_id = create_response.json()["id"]

    # Delete
    response = await client.delete(f"/enterprises/{enterprise_id}", headers=auth_headers)
    assert response.status_code == 204

    # Verify it's archived
    get_response = await client.get(f"/enterprises/{enterprise_id}", headers=auth_headers)
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_tenant_isolation_enterprises(client, auth_headers, viewer_headers):
    """Test that enterprises are isolated between tenants."""
    # Admin tenant creates enterprise
    admin_payload = {"name": "Admin Company"}
    admin_response = await client.post("/enterprises", json=admin_payload, headers=auth_headers)
    assert admin_response.status_code == 201

    # Viewer (different tenant) shouldn't see it
    viewer_response = await client.get("/enterprises", headers=viewer_headers)
    assert viewer_response.status_code == 200
    assert viewer_response.json() == []


@pytest.mark.asyncio
async def test_enterprises_pagination(client, auth_headers):
    """Test pagination of enterprises list."""
    # Create 15 enterprises
    for i in range(15):
        payload = {"name": f"Company {i+1}"}
        await client.post("/enterprises", json=payload, headers=auth_headers)

    # Get first page (default limit=10)
    response = await client.get("/enterprises?skip=0&limit=10", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 10

    # Get second page
    response = await client.get("/enterprises?skip=10&limit=10", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 5


@pytest.mark.asyncio
async def test_enterprise_unauthenticated(client):
    """Test that unauthenticated requests are rejected."""
    response = await client.get("/enterprises")
    assert response.status_code == 401
