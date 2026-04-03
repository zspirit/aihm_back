"""Tests for Twilio webhook endpoints (webhooks.py)."""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.position import Position

from tests.conftest import _create_user, TestSession


@pytest.fixture(autouse=True)
def mock_telephony_workers():
    """Mock telephony worker tasks called by webhook endpoints."""
    with (
        patch("app.workers.telephony.handle_call_status.delay", MagicMock()) as m_status,
        patch("app.workers.telephony.handle_recording_ready.delay", MagicMock()) as m_rec,
    ):
        yield m_status, m_rec


@pytest.fixture(autouse=True)
def _patch_voice_session():
    """Patch async_session in webhooks module to use test DB engine."""
    with patch("app.api.v1.webhooks.async_session", TestSession):
        yield


# --- Twilio status callback ---

@pytest.mark.asyncio
async def test_twilio_status_completed(client, mock_telephony_workers):
    m_status, _ = mock_telephony_workers
    resp = await client.post(
        "/api/v1/webhooks/twilio/status",
        data={"CallSid": "CA123", "CallStatus": "completed", "CallDuration": "120"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    m_status.assert_called_once_with("CA123", "completed", 120)


@pytest.mark.asyncio
async def test_twilio_status_failed(client, mock_telephony_workers):
    m_status, _ = mock_telephony_workers
    resp = await client.post(
        "/api/v1/webhooks/twilio/status",
        data={"CallSid": "CA456", "CallStatus": "failed", "CallDuration": "0"},
    )
    assert resp.status_code == 200
    m_status.assert_called_once_with("CA456", "failed", 0)


@pytest.mark.asyncio
async def test_twilio_status_busy(client, mock_telephony_workers):
    m_status, _ = mock_telephony_workers
    resp = await client.post(
        "/api/v1/webhooks/twilio/status",
        data={"CallSid": "CA789", "CallStatus": "busy", "CallDuration": "0"},
    )
    assert resp.status_code == 200
    m_status.assert_called_once_with("CA789", "busy", 0)


@pytest.mark.asyncio
async def test_twilio_status_no_answer(client, mock_telephony_workers):
    m_status, _ = mock_telephony_workers
    resp = await client.post(
        "/api/v1/webhooks/twilio/status",
        data={"CallSid": "CA000", "CallStatus": "no-answer", "CallDuration": "0"},
    )
    assert resp.status_code == 200
    m_status.assert_called_once_with("CA000", "no-answer", 0)


@pytest.mark.asyncio
async def test_twilio_status_empty_payload(client, mock_telephony_workers):
    """Empty form defaults should still work (all defaults)."""
    m_status, _ = mock_telephony_workers
    resp = await client.post("/api/v1/webhooks/twilio/status", data={})
    assert resp.status_code == 200
    m_status.assert_called_once_with("", "", 0)


# --- Twilio recording callback ---

@pytest.mark.asyncio
async def test_twilio_recording_callback(client, mock_telephony_workers):
    _, m_rec = mock_telephony_workers
    resp = await client.post(
        "/api/v1/webhooks/twilio/recording",
        data={
            "CallSid": "CA123",
            "RecordingUrl": "https://api.twilio.com/rec/RE123",
            "RecordingSid": "RE123",
            "RecordingDuration": "300",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    m_rec.assert_called_once_with(
        "CA123", "https://api.twilio.com/rec/RE123", "RE123", 300
    )


@pytest.mark.asyncio
async def test_twilio_recording_empty_payload(client, mock_telephony_workers):
    _, m_rec = mock_telephony_workers
    resp = await client.post("/api/v1/webhooks/twilio/recording", data={})
    assert resp.status_code == 200
    m_rec.assert_called_once_with("", "", "", 0)


# --- TwiML voice handler ---

@pytest.mark.asyncio
async def test_voice_handler_no_interview(client):
    """Without interview_id, returns default TwiML with generic greeting."""
    resp = await client.post("/api/v1/webhooks/twilio/voice")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    body = resp.text
    assert "<Response>" in body
    assert "Bonjour candidat" in body
    assert "Question" not in body


@pytest.mark.asyncio
async def test_voice_handler_with_interview(client, _setup_db):
    """With a valid interview_id, returns TwiML with questions."""
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "voice@test.com", "admin")

        position = Position(
            tenant_id=tenant.id,
            title="Dev",
            description="test",
            required_skills=["python"],
            custom_questions=[],
            created_by=user.id,
        )
        session.add(position)
        await session.flush()

        candidate = Candidate(
            tenant_id=tenant.id,
            name="Bob Martin",
            email="bob@test.com",
            position_id=position.id,
        )
        session.add(candidate)
        await session.flush()

        interview = Interview(
            candidate_id=candidate.id,
            position_id=position.id,
            tenant_id=tenant.id,
            status="in_progress",
            questions_asked=[
                {"text": "Parlez-moi de Python", "expected_duration_seconds": 30},
                "Question simple sans dict",
            ],
        )
        session.add(interview)
        await session.commit()
        interview_id = interview.id

    resp = await client.post(
        f"/api/v1/webhooks/twilio/voice?interview_id={interview_id}"
    )
    assert resp.status_code == 200
    body = resp.text
    assert "Bob Martin" in body
    assert "Question 1" in body
    assert "Parlez-moi de Python" in body
    assert "Question 2" in body
    assert "Question simple sans dict" in body
    assert 'length="30"' in body  # custom duration from dict


@pytest.mark.asyncio
async def test_voice_handler_invalid_interview_id(client):
    """With a non-existent interview_id, returns default TwiML."""
    fake_id = str(uuid.uuid4())
    resp = await client.post(f"/api/v1/webhooks/twilio/voice?interview_id={fake_id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Bonjour candidat" in body
    assert "Question" not in body
