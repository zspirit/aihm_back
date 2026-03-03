import pytest


@pytest.mark.asyncio
async def test_get_settings(client, auth_headers):
    """GET /api/v1/settings should return tenant settings."""
    response = await client.get("/api/v1/settings", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "name" in data
    assert "plan" in data
    assert "timezone" in data
    assert "data_retention_days" in data
    assert "max_interview_duration" in data


@pytest.mark.asyncio
async def test_get_settings_default_values(client, auth_headers):
    """GET /api/v1/settings should include default values for new tenant."""
    response = await client.get("/api/v1/settings", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Corp"
    assert data["timezone"] == "Africa/Casablanca"
    assert data["data_retention_days"] == 180
    assert data["max_interview_duration"] == 600


@pytest.mark.asyncio
async def test_get_compliance(client, auth_headers):
    """GET /api/v1/settings/compliance should return compliance info."""
    response = await client.get("/api/v1/settings/compliance", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "legal_framework" in data
    assert "Loi 09-08" in data["legal_framework"]
    assert data["consent_required"] is True
    assert data["audit_logging"] is True
    assert "regulatory_body" in data
    assert "CNDP" in data["regulatory_body"]
    assert data["telecom_authority"] == "ANRT"
    assert "data_encryption" in data
    assert data["data_retention_days"] == 180
    assert data["total_audit_entries"] >= 0


@pytest.mark.asyncio
async def test_settings_unauthenticated(client):
    """GET /api/v1/settings without auth should return 401."""
    response = await client.get("/api/v1/settings")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_compliance_unauthenticated(client):
    """GET /api/v1/settings/compliance without auth should return 401."""
    response = await client.get("/api/v1/settings/compliance")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_settings_as_admin(client, auth_headers):
    """PATCH /api/v1/settings as admin should update tenant settings."""
    response = await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"name": "Updated Corp", "timezone": "Europe/Paris"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Corp"
    assert data["timezone"] == "Europe/Paris"


@pytest.mark.asyncio
async def test_update_settings_as_viewer_forbidden(client, viewer_headers):
    """PATCH /api/v1/settings as viewer should return 403."""
    response = await client.patch(
        "/api/v1/settings",
        headers=viewer_headers,
        json={"name": "Hack Corp"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_settings_unauthenticated(client):
    """PATCH /api/v1/settings without auth should return 401."""
    response = await client.patch(
        "/api/v1/settings",
        json={"name": "No Auth Corp"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_settings_invalid_color(client, auth_headers):
    """PATCH /api/v1/settings with invalid primary_color should return 422."""
    response = await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"primary_color": "not-a-color"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_valid_color(client, auth_headers):
    """PATCH /api/v1/settings with valid primary_color should succeed."""
    response = await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"primary_color": "#FF5733"},
    )
    assert response.status_code == 200
    assert response.json()["primary_color"] == "#FF5733"


@pytest.mark.asyncio
async def test_update_settings_retention_too_low(client, auth_headers):
    """PATCH /api/v1/settings with data_retention_days < 30 should return 422."""
    response = await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"data_retention_days": 10},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_retention_too_high(client, auth_headers):
    """PATCH /api/v1/settings with data_retention_days > 730 should return 422."""
    response = await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"data_retention_days": 1000},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_interview_duration_too_low(client, auth_headers):
    """PATCH /api/v1/settings with max_interview_duration < 120 should return 422."""
    response = await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"max_interview_duration": 60},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_interview_duration_too_high(client, auth_headers):
    """PATCH /api/v1/settings with max_interview_duration > 1800 should return 422."""
    response = await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"max_interview_duration": 3600},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_viewer_can_read_settings(client, viewer_headers):
    """Viewer role should be able to read settings (get_current_user, not require_role)."""
    response = await client.get("/api/v1/settings", headers=viewer_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_viewer_can_read_compliance(client, viewer_headers):
    """Viewer role should be able to read compliance info."""
    response = await client.get("/api/v1/settings/compliance", headers=viewer_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["consent_required"] is True
