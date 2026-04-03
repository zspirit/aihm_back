import uuid

import pytest
import pytest_asyncio

from app.models.analysis import Analysis
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.position import Position
from app.models.report import Report

from tests.conftest import _create_user, TestSession


@pytest_asyncio.fixture()
async def auth_headers(_setup_db):
    async with TestSession() as session:
        headers, _, _ = await _create_user(session, "auth@test.com", "admin")
    return headers


@pytest_asyncio.fixture()
async def report_data(_setup_db):
    """Create a full chain: tenant > user > position > candidate > interview > report + analysis."""
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "report@test.com", "admin")

        position = Position(
            tenant_id=tenant.id,
            title="Dev Python",
            description="Poste dev",
            required_skills=["python"],
            custom_questions=[],
            created_by=user.id,
        )
        session.add(position)
        await session.flush()

        candidate = Candidate(
            tenant_id=tenant.id,
            name="Alice Dupont",
            email="alice@test.com",
            position_id=position.id,
        )
        session.add(candidate)
        await session.flush()

        interview = Interview(
            candidate_id=candidate.id,
            position_id=position.id,
            tenant_id=tenant.id,
            status="completed",
        )
        session.add(interview)
        await session.flush()

        report = Report(
            candidate_id=candidate.id,
            interview_id=interview.id,
            content={"summary": "Candidat solide avec bonnes competences techniques."},
            pdf_file_path="/reports/alice.pdf",
        )
        session.add(report)

        analysis = Analysis(
            interview_id=interview.id,
            scores={"global": 82.5, "technique": 85},
        )
        session.add(analysis)
        await session.commit()

        result = {
            "headers": headers,
            "position_id": str(position.id),
            "report_id": str(report.id),
        }
    return result


@pytest.mark.asyncio
async def test_list_reports_empty(client, auth_headers):
    resp = await client.get("/api/v1/reports", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["page_size"] == 20


@pytest.mark.asyncio
async def test_list_reports_with_data(client, report_data):
    resp = await client.get("/api/v1/reports", headers=report_data["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["candidate_name"] == "Alice Dupont"
    assert item["position_title"] == "Dev Python"
    assert item["global_score"] == 82.5
    assert item["has_pdf"] is True
    assert "Candidat solide" in item["summary"]


@pytest.mark.asyncio
async def test_list_reports_filter_by_position(client, report_data):
    pid = report_data["position_id"]
    resp = await client.get(f"/api/v1/reports?position_id={pid}", headers=report_data["headers"])
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    fake_pid = str(uuid.uuid4())
    resp2 = await client.get(f"/api/v1/reports?position_id={fake_pid}", headers=report_data["headers"])
    assert resp2.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_reports_filter_by_candidate_name(client, report_data):
    resp = await client.get("/api/v1/reports?candidate_name=alice", headers=report_data["headers"])
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    resp2 = await client.get("/api/v1/reports?candidate_name=bob", headers=report_data["headers"])
    assert resp2.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_reports_pagination(client, report_data):
    resp = await client.get("/api/v1/reports?page=1&page_size=1", headers=report_data["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["page_size"] == 1
    assert len(data["items"]) == 1

    resp2 = await client.get("/api/v1/reports?page=2&page_size=1", headers=report_data["headers"])
    assert resp2.json()["items"] == []


@pytest.mark.asyncio
async def test_get_report_detail(client, report_data):
    rid = report_data["report_id"]
    resp = await client.get(f"/api/v1/reports/{rid}", headers=report_data["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == rid
    assert data["content"]["summary"] == "Candidat solide avec bonnes competences techniques."
    assert data["pdf_file_path"] == "/reports/alice.pdf"


@pytest.mark.asyncio
async def test_get_report_not_found(client, auth_headers):
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/reports/{fake_id}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Rapport introuvable"


@pytest.mark.asyncio
async def test_get_report_other_tenant(client, report_data, _setup_db):
    """A user from another tenant should not see this report (gets 404)."""
    async with TestSession() as session:
        other_headers, _, _ = await _create_user(session, "other@other.com", "admin", "Other Corp")
    rid = report_data["report_id"]
    resp = await client.get(f"/api/v1/reports/{rid}", headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_reports_tenant_isolation(client, report_data, _setup_db):
    """Another tenant should see 0 reports."""
    async with TestSession() as session:
        other_headers, _, _ = await _create_user(session, "other2@other.com", "admin", "Other Corp 2")
    resp = await client.get("/api/v1/reports", headers=other_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_reports_unauthenticated(client, _setup_db):
    resp = await client.get("/api/v1/reports")
    assert resp.status_code in (401, 403)
