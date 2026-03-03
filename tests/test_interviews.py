import uuid

import pytest


@pytest.mark.asyncio
async def test_list_interviews_empty(client, auth_headers):
    """GET /api/v1/interviews should return paginated list (empty when no data)."""
    response = await client.get("/api/v1/interviews", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert data["total"] == 0
    assert data["items"] == []
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_list_interviews_with_status_filter(client, auth_headers):
    """GET /api/v1/interviews?status=completed should filter by status."""
    response = await client.get("/api/v1/interviews?status=completed", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_list_interviews_with_pagination(client, auth_headers):
    """GET /api/v1/interviews with pagination params should be accepted."""
    response = await client.get(
        "/api/v1/interviews?page=1&page_size=10", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 1
    assert data["page_size"] == 10


@pytest.mark.asyncio
async def test_list_interviews_with_sort(client, auth_headers):
    """GET /api/v1/interviews with sort params should be accepted."""
    response = await client.get(
        "/api/v1/interviews?sort_by=created_at&sort_order=asc", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_nonexistent_interview(client, auth_headers):
    """GET /api/v1/interviews/{id} with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/v1/interviews/{fake_id}", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Interview introuvable"


@pytest.mark.asyncio
async def test_reschedule_nonexistent_interview(client, auth_headers):
    """PATCH /api/v1/interviews/{id} with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.patch(
        f"/api/v1/interviews/{fake_id}",
        headers=auth_headers,
        json={"scheduled_at": "2025-06-01T10:00:00Z"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Interview introuvable"


@pytest.mark.asyncio
async def test_cancel_nonexistent_interview(client, auth_headers):
    """DELETE /api/v1/interviews/{id} with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.delete(
        f"/api/v1/interviews/{fake_id}", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Interview introuvable"


@pytest.mark.asyncio
async def test_get_transcription_nonexistent_interview(client, auth_headers):
    """GET /api/v1/interviews/{id}/transcription with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(
        f"/api/v1/interviews/{fake_id}/transcription", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Interview introuvable"


@pytest.mark.asyncio
async def test_get_analysis_nonexistent_interview(client, auth_headers):
    """GET /api/v1/interviews/{id}/analysis with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(
        f"/api/v1/interviews/{fake_id}/analysis", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Interview introuvable"


@pytest.mark.asyncio
async def test_get_report_nonexistent_interview(client, auth_headers):
    """GET /api/v1/interviews/{id}/report with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(
        f"/api/v1/interviews/{fake_id}/report", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Interview introuvable"


@pytest.mark.asyncio
async def test_get_audio_nonexistent_interview(client, auth_headers):
    """GET /api/v1/interviews/{id}/audio with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(
        f"/api/v1/interviews/{fake_id}/audio", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Interview introuvable"


@pytest.mark.asyncio
async def test_download_report_nonexistent_interview(client, auth_headers):
    """GET /api/v1/interviews/{id}/report/download with invalid ID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(
        f"/api/v1/interviews/{fake_id}/report/download", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Interview introuvable"


@pytest.mark.asyncio
async def test_viewer_reschedule_returns_404_different_tenant(client, viewer_headers):
    """Viewer in different tenant gets 404 when trying to reschedule (tenant isolation)."""
    fake_id = str(uuid.uuid4())
    response = await client.patch(
        f"/api/v1/interviews/{fake_id}",
        headers=viewer_headers,
        json={"scheduled_at": "2025-06-01T10:00:00Z"},
    )
    # Viewer is in a different tenant, so interview is not found
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_viewer_cancel_returns_404_different_tenant(client, viewer_headers):
    """Viewer in different tenant gets 404 when trying to cancel (tenant isolation)."""
    fake_id = str(uuid.uuid4())
    response = await client.delete(
        f"/api/v1/interviews/{fake_id}", headers=viewer_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_interviews_unauthenticated(client):
    """GET /api/v1/interviews without auth should return 401."""
    response = await client.get("/api/v1/interviews")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reschedule_invalid_uuid(client, auth_headers):
    """PATCH /api/v1/interviews/{id} with invalid UUID format should return 422."""
    response = await client.patch(
        "/api/v1/interviews/not-a-uuid",
        headers=auth_headers,
        json={"scheduled_at": "2025-06-01T10:00:00Z"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reschedule_missing_body(client, auth_headers):
    """PATCH /api/v1/interviews/{id} without body should return 422."""
    fake_id = str(uuid.uuid4())
    response = await client.patch(
        f"/api/v1/interviews/{fake_id}",
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_schedule_interview_nonexistent_candidate(client, auth_headers):
    """POST /api/v1/candidates/{id}/interviews with invalid candidate should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.post(
        f"/api/v1/candidates/{fake_id}/interviews",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Candidat introuvable"


@pytest.mark.asyncio
async def test_list_interviews_with_position_filter(client, auth_headers):
    """GET /api/v1/interviews?position_id=... should accept filter."""
    fake_pos_id = str(uuid.uuid4())
    response = await client.get(
        f"/api/v1/interviews?position_id={fake_pos_id}", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_interviews_with_date_filters(client, auth_headers):
    """GET /api/v1/interviews with date_from and date_to should accept filters."""
    response = await client.get(
        "/api/v1/interviews?date_from=2025-01-01T00:00:00Z&date_to=2025-12-31T23:59:59Z",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_interviews_with_candidate_name_filter(client, auth_headers):
    """GET /api/v1/interviews?candidate_name=... should accept filter."""
    response = await client.get(
        "/api/v1/interviews?candidate_name=Ali", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0
