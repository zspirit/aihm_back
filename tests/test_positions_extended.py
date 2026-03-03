import uuid

import pytest


@pytest.mark.asyncio
async def test_create_position_minimal(client, auth_headers):
    """Creating a position with just a title should succeed with defaults."""
    response = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={"title": "Poste Minimal"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Poste Minimal"
    assert data["description"] == ""
    assert data["seniority_level"] == "mid"
    assert data["required_skills"] == []
    assert data["custom_questions"] == []
    assert data["status"] == "draft"
    assert data["auto_advance_threshold"] is None
    assert data["auto_reject_threshold"] is None


@pytest.mark.asyncio
async def test_create_position_with_thresholds(client, auth_headers):
    """Creating a position with auto_advance and auto_reject thresholds."""
    response = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={
            "title": "Dev Python",
            "description": "Test position",
            "auto_advance_threshold": 80,
            "auto_reject_threshold": 30,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["auto_advance_threshold"] == 80
    assert data["auto_reject_threshold"] == 30


@pytest.mark.asyncio
async def test_create_position_threshold_over_100(client, auth_headers):
    """auto_advance_threshold > 100 should fail validation (ge=0, le=100)."""
    response = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={
            "title": "Dev Python",
            "auto_advance_threshold": 150,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_position_threshold_negative(client, auth_headers):
    """auto_reject_threshold < 0 should fail validation (ge=0, le=100)."""
    response = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={
            "title": "Dev Python",
            "auto_reject_threshold": -10,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_position_with_deadline(client, auth_headers):
    """Creating a position with a deadline."""
    response = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={
            "title": "Dev React",
            "deadline": "2025-12-31T23:59:59Z",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["deadline"] is not None


@pytest.mark.asyncio
async def test_create_position_with_skills_as_strings(client, auth_headers):
    """Creating a position with old format skills (list of strings) should normalize."""
    response = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={
            "title": "Dev Full Stack",
            "required_skills": ["Python", "React", "PostgreSQL"],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert len(data["required_skills"]) == 3
    # Each skill should be normalized to a dict with name, level_required, etc.
    for skill in data["required_skills"]:
        assert "name" in skill
        assert "level_required" in skill


@pytest.mark.asyncio
async def test_create_position_with_skills_as_dicts(client, auth_headers):
    """Creating a position with new format skills (list of dicts)."""
    response = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={
            "title": "Data Engineer",
            "required_skills": [
                {"name": "Python", "level_required": 4, "weight": 3, "category": "technique"},
                {"name": "SQL", "level_required": 3, "weight": 2, "category": "technique"},
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert len(data["required_skills"]) == 2
    assert data["required_skills"][0]["name"] == "Python"
    assert data["required_skills"][0]["level_required"] == 4


@pytest.mark.asyncio
async def test_duplicate_nonexistent_position(client, auth_headers):
    """POST /api/v1/positions/{id}/duplicate with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.post(
        f"/api/v1/positions/{fake_id}/duplicate", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Poste introuvable"


@pytest.mark.asyncio
async def test_duplicate_position(client, auth_headers):
    """Duplicating a position should create a copy with 'Copie de -' prefix."""
    create_res = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={
            "title": "Dev Original",
            "description": "Description originale",
            "required_skills": ["Python"],
            "seniority_level": "senior",
        },
    )
    assert create_res.status_code == 201
    pos_id = create_res.json()["id"]

    dup_res = await client.post(
        f"/api/v1/positions/{pos_id}/duplicate", headers=auth_headers
    )
    assert dup_res.status_code == 201
    data = dup_res.json()
    assert data["title"] == "Copie de - Dev Original"
    assert data["description"] == "Description originale"
    assert data["status"] == "draft"
    assert data["id"] != pos_id


@pytest.mark.asyncio
async def test_duplicate_position_with_custom_title(client, auth_headers):
    """Duplicating a position with a custom title."""
    create_res = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={"title": "Dev Python"},
    )
    pos_id = create_res.json()["id"]

    dup_res = await client.post(
        f"/api/v1/positions/{pos_id}/duplicate",
        headers=auth_headers,
        json={"title": "Dev Python v2"},
    )
    assert dup_res.status_code == 201
    assert dup_res.json()["title"] == "Dev Python v2"


@pytest.mark.asyncio
async def test_optimize_nonexistent_position(client, auth_headers):
    """POST /api/v1/positions/{id}/optimize with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.post(
        f"/api/v1/positions/{fake_id}/optimize", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Poste introuvable"


@pytest.mark.asyncio
async def test_list_templates(client, auth_headers):
    """GET /api/v1/positions/templates should return a list of templates."""
    response = await client.get("/api/v1/positions/templates", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_viewer_cannot_create_position(client, viewer_headers):
    """Viewer role should not be able to create positions."""
    response = await client.post(
        "/api/v1/positions",
        headers=viewer_headers,
        json={"title": "Nope", "description": "Test"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_delete_position(client, viewer_headers):
    """Viewer role should not be able to delete positions."""
    fake_id = str(uuid.uuid4())
    response = await client.delete(
        f"/api/v1/positions/{fake_id}", headers=viewer_headers
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_update_position(client, viewer_headers):
    """Viewer role should not be able to update positions."""
    fake_id = str(uuid.uuid4())
    response = await client.put(
        f"/api/v1/positions/{fake_id}",
        headers=viewer_headers,
        json={"title": "Updated"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_duplicate_position(client, viewer_headers):
    """Viewer role should not be able to duplicate positions."""
    fake_id = str(uuid.uuid4())
    response = await client.post(
        f"/api/v1/positions/{fake_id}/duplicate", headers=viewer_headers
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_viewer_can_list_positions(client, auth_headers, viewer_headers):
    """Viewer role should be able to list positions (read-only)."""
    response = await client.get("/api/v1/positions", headers=viewer_headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_search_positions(client, auth_headers):
    """Search positions by title."""
    await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={"title": "Developpeur React Senior", "description": "Frontend position"},
    )
    await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={"title": "Data Scientist", "description": "ML position"},
    )

    response = await client.get("/api/v1/positions?search=React", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any("React" in item["title"] for item in data["items"])


@pytest.mark.asyncio
async def test_search_positions_in_description(client, auth_headers):
    """Search positions by description content."""
    await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={"title": "Ingenieur", "description": "Travail sur des microservices Kubernetes"},
    )

    response = await client.get(
        "/api/v1/positions?search=kubernetes", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_nonexistent_position(client, auth_headers):
    """GET /api/v1/positions/{id} with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(
        f"/api/v1/positions/{fake_id}", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Poste introuvable"


@pytest.mark.asyncio
async def test_update_nonexistent_position(client, auth_headers):
    """PUT /api/v1/positions/{id} with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.put(
        f"/api/v1/positions/{fake_id}",
        headers=auth_headers,
        json={"title": "Updated"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Poste introuvable"


@pytest.mark.asyncio
async def test_delete_nonexistent_position(client, auth_headers):
    """DELETE /api/v1/positions/{id} with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.delete(
        f"/api/v1/positions/{fake_id}", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Poste introuvable"


@pytest.mark.asyncio
async def test_create_position_invalid_skill_category(client, auth_headers):
    """Creating a position with invalid skill category should fail validation."""
    response = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={
            "title": "Test",
            "required_skills": [
                {"name": "Python", "category": "invalid_category"},
            ],
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_position_unauthenticated(client):
    """POST /api/v1/positions without auth should return 401."""
    response = await client.post(
        "/api/v1/positions",
        json={"title": "Test"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_position_candidate_count(client, auth_headers):
    """Position response should include candidate_count."""
    create_res = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={"title": "Poste avec candidats"},
    )
    assert create_res.status_code == 201
    pos_id = create_res.json()["id"]

    # Initially 0 candidates
    get_res = await client.get(f"/api/v1/positions/{pos_id}", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["candidate_count"] == 0

    # Add a candidate
    await client.post(
        f"/api/v1/positions/{pos_id}/candidates",
        headers=auth_headers,
        data={"name": "Ali"},
    )

    # Now 1 candidate
    get_res = await client.get(f"/api/v1/positions/{pos_id}", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["candidate_count"] == 1


@pytest.mark.asyncio
async def test_update_position_status(client, auth_headers):
    """Updating position status from draft to active."""
    create_res = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={"title": "Draft Position"},
    )
    pos_id = create_res.json()["id"]
    assert create_res.json()["status"] == "draft"

    update_res = await client.put(
        f"/api/v1/positions/{pos_id}",
        headers=auth_headers,
        json={"status": "active"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "active"


@pytest.mark.asyncio
async def test_list_positions_empty(client, auth_headers):
    """GET /api/v1/positions with no positions should return empty list."""
    response = await client.get("/api/v1/positions", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["page"] == 1
