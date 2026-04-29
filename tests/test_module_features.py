import pytest

from app.schemas.tenant import MODULE_KEYS


@pytest.mark.asyncio
async def test_module_enabled_by_default(client, auth_headers):
    """Module activé par défaut (modules_config vide) → GET settings shows null/empty modules_config."""
    response = await client.get("/api/v1/settings", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    # modules_config is null or empty by default, meaning all modules are enabled
    assert data.get("modules_config") is None or data.get("modules_config") == {}


@pytest.mark.asyncio
async def test_patch_settings_modules_config(client, auth_headers):
    """PATCH /api/v1/settings with modules_config persists correctly."""
    response = await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={
            "modules_config": {
                "ai_phone_interview": False,
                "matching_nm": False,
            }
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["modules_config"]["ai_phone_interview"] is False
    assert data["modules_config"]["matching_nm"] is False

    # Verify GET returns the same persisted config
    response = await client.get("/api/v1/settings", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["modules_config"]["ai_phone_interview"] is False


@pytest.mark.asyncio
async def test_patch_settings_modules_config_re_enable(client, auth_headers):
    """PATCH modules_config can re-enable a previously disabled module."""
    # First disable it
    await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"modules_config": {"analytics": False}},
    )

    # Then re-enable it
    response = await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"modules_config": {"analytics": True}},
    )
    assert response.status_code == 200
    assert response.json()["modules_config"]["analytics"] is True


@pytest.mark.asyncio
async def test_schedule_interview_with_module_disabled_raises_403(client, auth_headers, db_session):
    """POST /candidates/{id}/interviews with ai_phone_interview disabled → 403."""
    import uuid
    from app.models.candidate import Candidate
    from app.models.tenant import Tenant
    from app.core.security import decode_token
    from sqlalchemy import select

    # Get tenant from auth token
    token = auth_headers["Authorization"].split(" ")[1]
    payload = decode_token(token)
    tenant_id = payload["tenant_id"]

    # Disable the module
    await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"modules_config": {"ai_phone_interview": False}},
    )

    # Create a candidate
    candidate = Candidate(
        tenant_id=uuid.UUID(tenant_id),
        name="Test Candidat",
        email="candidat@test.com",
        phone="+33612345678",
    )
    db_session.add(candidate)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/candidates/{candidate.id}/interviews",
        headers=auth_headers,
        json={"phone": "+33612345678"},
    )
    assert response.status_code == 403
    assert "désactivé" in response.json()["detail"]


@pytest.mark.asyncio
async def test_schedule_interview_with_module_enabled_proceeds(client, auth_headers, db_session):
    """POST /candidates/{id}/interviews with ai_phone_interview enabled → not 403."""
    import uuid
    from app.models.candidate import Candidate
    from app.core.security import decode_token

    token = auth_headers["Authorization"].split(" ")[1]
    payload = decode_token(token)
    tenant_id = payload["tenant_id"]

    # Ensure module is enabled
    await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"modules_config": {"ai_phone_interview": True}},
    )

    # Create candidate without phone to get 400 (not 403)
    candidate = Candidate(
        tenant_id=uuid.UUID(tenant_id),
        name="Candidat Sans Phone",
        email="nophone@test.com",
    )
    db_session.add(candidate)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/candidates/{candidate.id}/interviews",
        headers=auth_headers,
        json={},
    )
    # 400 means module gate passed (phone missing), not 403 (module disabled)
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_all_module_keys_documented():
    """Tous les MODULE_KEYS sont présents et correspondent aux modules attendus."""
    expected_keys = {
        "cv_scoring", "ai_phone_interview", "report_generation",
        "candidate_feedback", "matching_nm", "collaborative_scorecard",
        "bulk_import", "analytics", "copilot", "webhooks",
        "consent_gdpr", "anonymizer",
    }
    assert set(MODULE_KEYS) == expected_keys


@pytest.mark.asyncio
async def test_matching_module_disabled_raises_403(client, auth_headers):
    """POST /api/v1/positions/{id}/match with matching_nm disabled → 403."""
    import uuid

    await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"modules_config": {"matching_nm": False}},
    )

    fake_id = str(uuid.uuid4())
    response = await client.post(
        f"/api/v1/positions/{fake_id}/match",
        headers=auth_headers,
    )
    assert response.status_code == 403
    assert "désactivé" in response.json()["detail"]


@pytest.mark.asyncio
async def test_viewer_cannot_change_modules_config(client, auth_headers, viewer_headers):
    """Viewer role cannot change modules_config (403 Forbidden)."""
    response = await client.patch(
        "/api/v1/settings",
        headers=viewer_headers,
        json={"modules_config": {"analytics": False}},
    )
    assert response.status_code == 403
