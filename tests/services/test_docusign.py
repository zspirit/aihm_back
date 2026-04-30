"""Unit tests for the DocuSign integration service."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.services import docusign


@pytest.fixture(autouse=True)
def _clear_token_cache():
    docusign._token_cache = None
    yield
    docusign._token_cache = None


@pytest.fixture
def configured_settings():
    """All required settings present."""
    with patch("app.services.docusign.get_settings") as gs:
        s = MagicMock()
        s.DOCUSIGN_INTEGRATION_KEY = "ik-123"
        s.DOCUSIGN_USER_ID = "user-456"
        s.DOCUSIGN_ACCOUNT_ID = "account-789"
        # A fake but valid-shaped RSA key would be needed for real signing;
        # tests stub _build_jwt instead.
        s.DOCUSIGN_PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"
        s.DOCUSIGN_AUTH_HOST = "account-d.docusign.com"
        s.DOCUSIGN_API_HOST = "demo.docusign.net"
        gs.return_value = s
        yield s


@pytest.fixture
def unconfigured_settings():
    with patch("app.services.docusign.get_settings") as gs:
        s = MagicMock()
        s.DOCUSIGN_INTEGRATION_KEY = ""
        s.DOCUSIGN_USER_ID = ""
        s.DOCUSIGN_ACCOUNT_ID = ""
        s.DOCUSIGN_PRIVATE_KEY = ""
        gs.return_value = s
        yield s


# ─── _check_configured ────────────────────────────────────────────────────────


def test_check_configured_passes_when_all_set(configured_settings):
    docusign._check_configured()  # should not raise


def test_check_configured_raises_when_missing(unconfigured_settings):
    with pytest.raises(docusign.DocuSignNotConfigured) as exc:
        docusign._check_configured()
    msg = str(exc.value)
    # All four required fields should be reported as missing.
    assert "DOCUSIGN_INTEGRATION_KEY" in msg
    assert "DOCUSIGN_USER_ID" in msg
    assert "DOCUSIGN_ACCOUNT_ID" in msg
    assert "DOCUSIGN_PRIVATE_KEY" in msg


# ─── get_access_token ─────────────────────────────────────────────────────────


def test_get_access_token_unconfigured_raises(unconfigured_settings):
    with pytest.raises(docusign.DocuSignNotConfigured):
        docusign.get_access_token()


def test_get_access_token_caches_until_near_expiry(configured_settings):
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json = MagicMock(return_value={"access_token": "AT-1", "expires_in": 3600})

    mock_client = MagicMock()
    mock_client.post = MagicMock(return_value=fake_response)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("app.services.docusign._build_jwt", return_value="fake-jwt"):
        with patch("httpx.Client", return_value=mock_client):
            t1 = docusign.get_access_token()
            t2 = docusign.get_access_token()  # should hit cache, not POST again

    assert t1 == "AT-1"
    assert t2 == "AT-1"
    assert mock_client.post.call_count == 1  # cached on second call


def test_get_access_token_refreshes_after_expiry(configured_settings):
    docusign._token_cache = docusign._CachedToken(
        access_token="OLD",
        expires_at=time.time() - 10,  # already expired
    )

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json = MagicMock(return_value={"access_token": "NEW", "expires_in": 3600})

    mock_client = MagicMock()
    mock_client.post = MagicMock(return_value=fake_response)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("app.services.docusign._build_jwt", return_value="fake-jwt"):
        with patch("httpx.Client", return_value=mock_client):
            assert docusign.get_access_token() == "NEW"


def test_get_access_token_raises_on_token_endpoint_failure(configured_settings):
    fake_response = MagicMock()
    fake_response.status_code = 401
    fake_response.text = "consent_required"

    mock_client = MagicMock()
    mock_client.post = MagicMock(return_value=fake_response)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("app.services.docusign._build_jwt", return_value="fake-jwt"):
        with patch("httpx.Client", return_value=mock_client):
            with pytest.raises(docusign.DocuSignError, match="401"):
                docusign.get_access_token()


# ─── send_envelope_for_offer ──────────────────────────────────────────────────


def test_send_envelope_posts_correct_payload(configured_settings):
    create_response = MagicMock()
    create_response.status_code = 201
    create_response.json = MagicMock(return_value={"envelopeId": "env-1", "status": "sent"})

    mock_client = MagicMock()
    mock_client.post = MagicMock(return_value=create_response)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("app.services.docusign.get_access_token", return_value="AT"):
        with patch("httpx.Client", return_value=mock_client):
            result = docusign.send_envelope_for_offer(
                candidate_name="Alice",
                candidate_email="alice@x.com",
                position_title="Senior Backend",
                pdf_bytes=b"%PDF-1.4 fake",
            )

    assert result["envelopeId"] == "env-1"
    args, kwargs = mock_client.post.call_args
    assert "/envelopes" in args[0]
    assert kwargs["headers"]["Authorization"] == "Bearer AT"

    body = kwargs["json"]
    assert body["status"] == "sent"
    assert "Senior Backend" in body["emailSubject"]
    signer = body["recipients"]["signers"][0]
    assert signer["email"] == "alice@x.com"
    assert signer["name"] == "Alice"
    assert signer["tabs"]["signHereTabs"][0]["anchorString"] == "/sig1/"


def test_send_envelope_raises_on_non_2xx(configured_settings):
    fake_response = MagicMock()
    fake_response.status_code = 400
    fake_response.text = "INVALID_RECIPIENT"

    mock_client = MagicMock()
    mock_client.post = MagicMock(return_value=fake_response)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("app.services.docusign.get_access_token", return_value="AT"):
        with patch("httpx.Client", return_value=mock_client):
            with pytest.raises(docusign.DocuSignError, match="400"):
                docusign.send_envelope_for_offer(
                    candidate_name="X",
                    candidate_email="x@y.com",
                    position_title="P",
                    pdf_bytes=b"x",
                )


# ─── get_envelope_status ──────────────────────────────────────────────────────


def test_get_envelope_status_returns_provider_status(configured_settings):
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json = MagicMock(return_value={"status": "completed"})

    mock_client = MagicMock()
    mock_client.get = MagicMock(return_value=fake_response)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("app.services.docusign.get_access_token", return_value="AT"):
        with patch("httpx.Client", return_value=mock_client):
            assert docusign.get_envelope_status("env-1") == "completed"
