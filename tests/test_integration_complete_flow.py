"""Complete integration tests for the entire AIHM workflow."""
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4


@pytest.mark.asyncio
async def test_complete_recruitment_flow(client, auth_headers):
    """Test the complete recruitment flow from position creation to offer signing."""

    # 1. Create an enterprise
    enterprise_payload = {
        "name": "Integration Test Company",
        "industry": "Technology",
        "domain": "testco.com",
        "contact_email": "hr@testco.com",
    }
    enterprise_resp = await client.post("/enterprises", json=enterprise_payload, headers=auth_headers)
    assert enterprise_resp.status_code == 201
    enterprise_id = enterprise_resp.json()["id"]

    # 2. Create a position linked to the enterprise
    position_payload = {
        "title": "Senior Engineer",
        "description": "Build amazing things",
        "seniority_level": "senior",
        "enterprise_id": enterprise_id,
    }
    position_resp = await client.post("/positions", json=position_payload, headers=auth_headers)
    assert position_resp.status_code == 201
    position_id = position_resp.json()["id"]

    # 3. Create a candidate
    candidate_payload = {
        "email": "candidate@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "phone": "+1234567890",
    }
    candidate_resp = await client.post("/candidates", json=candidate_payload, headers=auth_headers)
    assert candidate_resp.status_code == 201
    candidate_id = candidate_resp.json()["id"]

    # 4. Create an application
    application_payload = {
        "position_id": position_id,
        "candidate_id": candidate_id,
    }
    application_resp = await client.post("/applications", json=application_payload, headers=auth_headers)
    assert application_resp.status_code == 201
    application_id = application_resp.json()["id"]

    # 5. Create an offer from the application
    offer_payload = {
        "salary_min": 80000,
        "salary_max": 120000,
        "currency": "EUR",
        "contract_type": "permanent",
        "benefits": "Health insurance, 30 days PTO",
    }
    offer_resp = await client.post(
        f"/applications/{application_id}/offers",
        json=offer_payload,
        headers=auth_headers,
    )
    assert offer_resp.status_code == 201
    offer_id = offer_resp.json()["id"]
    assert offer_resp.json()["status"] == "draft"

    # 6. Send the offer
    send_payload = {
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    }
    send_resp = await client.post(
        f"/offers/{offer_id}/send",
        json=send_payload,
        headers=auth_headers,
    )
    assert send_resp.status_code == 200
    assert send_resp.json()["status"] == "sent"
    signature_token = send_resp.json()["signature_token"]

    # 7. Mark offer as viewed
    viewed_resp = await client.post(
        f"/offers/{offer_id}/viewed",
        headers=auth_headers,
    )
    assert viewed_resp.status_code == 200
    assert viewed_resp.json()["status"] == "viewed"

    # 8. Sign the offer
    sign_payload = {
        "signature_token": signature_token,
        "signed_by": "John Doe",
    }
    sign_resp = await client.post(
        f"/offers/{offer_id}/sign",
        json=sign_payload,
    )
    assert sign_resp.status_code == 200
    assert sign_resp.json()["status"] == "signed"

    # 9. Verify application decision was updated
    application_resp = await client.get(f"/applications/{application_id}", headers=auth_headers)
    assert application_resp.status_code == 200
    assert application_resp.json()["decision"] == "accepted"

    # 10. Get offer metrics
    metrics_resp = await client.get(
        f"/metrics/enterprises/{enterprise_id}",
        headers=auth_headers,
    )
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.json()
    assert "name" in metrics
    assert "hired" in metrics
    assert metrics["hired"] >= 1


@pytest.mark.asyncio
async def test_offer_rejection_flow(client, auth_headers):
    """Test the offer rejection workflow."""

    # Setup: Create enterprise, position, candidate, application
    enterprise_payload = {"name": "Test Company"}
    enterprise_resp = await client.post("/enterprises", json=enterprise_payload, headers=auth_headers)
    enterprise_id = enterprise_resp.json()["id"]

    position_payload = {
        "title": "Test Position",
        "description": "Test",
        "seniority_level": "mid",
        "enterprise_id": enterprise_id,
    }
    position_resp = await client.post("/positions", json=position_payload, headers=auth_headers)
    position_id = position_resp.json()["id"]

    candidate_payload = {
        "email": "test@example.com",
        "first_name": "Test",
        "last_name": "Candidate",
    }
    candidate_resp = await client.post("/candidates", json=candidate_payload, headers=auth_headers)
    candidate_id = candidate_resp.json()["id"]

    application_payload = {
        "position_id": position_id,
        "candidate_id": candidate_id,
    }
    application_resp = await client.post("/applications", json=application_payload, headers=auth_headers)
    application_id = application_resp.json()["id"]

    # Create and send offer
    offer_payload = {"salary_min": 50000}
    offer_resp = await client.post(
        f"/applications/{application_id}/offers",
        json=offer_payload,
        headers=auth_headers,
    )
    offer_id = offer_resp.json()["id"]

    send_payload = {"expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()}
    await client.post(f"/offers/{offer_id}/send", json=send_payload, headers=auth_headers)

    # Reject offer
    reject_payload = {"rejection_reason": "Candidate declined"}
    reject_resp = await client.post(
        f"/offers/{offer_id}/reject",
        json=reject_payload,
        headers=auth_headers,
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"

    # Verify application decision was updated
    application_resp = await client.get(f"/applications/{application_id}", headers=auth_headers)
    assert application_resp.json()["decision"] == "rejected"


@pytest.mark.asyncio
async def test_analytics_overview(client, auth_headers):
    """Test analytics overview endpoint."""
    overview_resp = await client.get("/metrics/analytics/overview", headers=auth_headers)
    assert overview_resp.status_code == 200
    data = overview_resp.json()
    assert "period_days" in data
    assert "total_positions" in data
    assert "total_candidates" in data
    assert "recent_applications" in data
    assert "recent_interviews" in data
    assert "recent_offers" in data
    assert "recent_hired" in data


@pytest.mark.asyncio
async def test_unauthorized_access(client):
    """Test that unauthenticated requests are rejected."""
    endpoints = [
        "/offers",
        "/enterprises",
        "/positions",
        "/candidates",
        "/applications",
        "/metrics/analytics/overview",
    ]

    for endpoint in endpoints:
        resp = await client.get(endpoint)
        assert resp.status_code == 401
