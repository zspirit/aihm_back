"""Unit tests for the calendar OAuth helpers (no DB, no network)."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet

from app.services import calendar_oauth as oauth


@pytest.fixture
def with_fernet_key():
    """Activate token encryption for the duration of the test."""
    key = Fernet.generate_key().decode()
    with patch("app.services.calendar_oauth.get_settings") as gs:
        gs.return_value.ENCRYPTION_KEY = key
        gs.return_value.JWT_SECRET_KEY = "test-secret-please-do-not-reuse"
        gs.return_value.GOOGLE_CLIENT_ID = "google-id"
        gs.return_value.GOOGLE_CLIENT_SECRET = "google-secret"
        gs.return_value.MICROSOFT_CLIENT_ID = "ms-id"
        gs.return_value.MICROSOFT_CLIENT_SECRET = "ms-secret"
        gs.return_value.OAUTH_REDIRECT_BASE_URL = "http://localhost:5173"
        yield


@pytest.fixture
def no_fernet_key():
    """Run as if no encryption key is configured (dev mode)."""
    with patch("app.services.calendar_oauth.get_settings") as gs:
        gs.return_value.ENCRYPTION_KEY = ""
        gs.return_value.JWT_SECRET_KEY = "test-secret"
        gs.return_value.GOOGLE_CLIENT_ID = ""
        gs.return_value.MICROSOFT_CLIENT_ID = ""
        gs.return_value.OAUTH_REDIRECT_BASE_URL = "http://localhost:5173"
        yield


# ─── Encryption ───────────────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip(with_fernet_key):
    plaintext = "ya29.real-google-token"
    encrypted = oauth.encrypt_token(plaintext)
    assert encrypted != plaintext  # actually encrypted
    assert oauth.decrypt_token(encrypted) == plaintext


def test_encrypt_is_passthrough_when_no_key(no_fernet_key):
    """In dev with no key, tokens are stored as-is — never deploy without a key."""
    assert oauth.encrypt_token("token") == "token"
    assert oauth.decrypt_token("token") == "token"


def test_decrypt_raises_on_tampered_ciphertext(with_fernet_key):
    encrypted = oauth.encrypt_token("plain")
    tampered = encrypted[:-4] + "AAAA"
    with pytest.raises(ValueError):
        oauth.decrypt_token(tampered)


# ─── State token ──────────────────────────────────────────────────────────────


def test_make_state_round_trip(with_fernet_key):
    state = oauth.make_state("user-1", oauth.PROVIDER_GOOGLE)
    assert oauth.verify_state(state, "user-1", oauth.PROVIDER_GOOGLE) is True


def test_verify_state_rejects_tampered_signature(with_fernet_key):
    state = oauth.make_state("user-1", oauth.PROVIDER_GOOGLE)
    encoded, sig = state.rsplit(".", 1)
    bad = encoded + "." + ("A" * len(sig))
    assert oauth.verify_state(bad, "user-1", oauth.PROVIDER_GOOGLE) is False


def test_verify_state_rejects_wrong_user(with_fernet_key):
    state = oauth.make_state("user-1", oauth.PROVIDER_GOOGLE)
    assert oauth.verify_state(state, "user-2", oauth.PROVIDER_GOOGLE) is False


def test_verify_state_rejects_wrong_provider(with_fernet_key):
    state = oauth.make_state("user-1", oauth.PROVIDER_GOOGLE)
    assert oauth.verify_state(state, "user-1", oauth.PROVIDER_MICROSOFT) is False


def test_verify_state_rejects_expired(with_fernet_key):
    """An ancient state must be refused even if the signature is valid."""
    state = oauth.make_state("user-1", oauth.PROVIDER_GOOGLE)
    # Move time forward by TTL + 1s.
    with patch("app.services.calendar_oauth.time.time", return_value=time.time() + oauth.STATE_TTL_SECONDS + 1):
        assert oauth.verify_state(state, "user-1", oauth.PROVIDER_GOOGLE) is False


def test_verify_state_rejects_malformed(with_fernet_key):
    assert oauth.verify_state("not.a.token", "u", oauth.PROVIDER_GOOGLE) is False
    assert oauth.verify_state("missing-dot-sig", "u", oauth.PROVIDER_GOOGLE) is False


# ─── Authorize URL builders ───────────────────────────────────────────────────


def test_build_google_authorize_url_includes_required_params(with_fernet_key):
    url = oauth.build_google_authorize_url("user-1")
    assert url.startswith(oauth.GOOGLE_AUTH_URL)
    assert "client_id=google-id" in url
    assert "redirect_uri=" in url
    # %20 (URL-encoded space) is what urlencode produces for spaces
    assert "scope=" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=" in url


def test_build_google_authorize_url_raises_without_client_id(no_fernet_key):
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        oauth.build_google_authorize_url("user-1")


def test_build_microsoft_authorize_url_includes_required_params(with_fernet_key):
    url = oauth.build_microsoft_authorize_url("user-1")
    assert url.startswith(oauth.MICROSOFT_AUTH_URL)
    assert "client_id=ms-id" in url
    assert "scope=" in url
    assert "state=" in url


def test_build_microsoft_authorize_url_raises_without_client_id(no_fernet_key):
    with pytest.raises(RuntimeError, match="MICROSOFT_CLIENT_ID"):
        oauth.build_microsoft_authorize_url("user-1")


# ─── Token exchange (mocked HTTP) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exchange_google_code_posts_correct_payload(with_fernet_key):
    fake_response = AsyncMock()
    fake_response.raise_for_status = lambda: None
    fake_response.json = lambda: {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await oauth.exchange_google_code("auth-code-123")

    assert result["access_token"] == "AT"
    mock_client.post.assert_awaited_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == oauth.GOOGLE_TOKEN_URL
    assert kwargs["data"]["code"] == "auth-code-123"
    assert kwargs["data"]["grant_type"] == "authorization_code"
    assert kwargs["data"]["client_id"] == "google-id"


@pytest.mark.asyncio
async def test_exchange_microsoft_code_posts_correct_payload(with_fernet_key):
    fake_response = AsyncMock()
    fake_response.raise_for_status = lambda: None
    fake_response.json = lambda: {"access_token": "MAT", "refresh_token": "MRT"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await oauth.exchange_microsoft_code("ms-code")

    assert result["access_token"] == "MAT"
    args, kwargs = mock_client.post.call_args
    assert args[0] == oauth.MICROSOFT_TOKEN_URL
    assert kwargs["data"]["code"] == "ms-code"
    assert "Calendars.ReadWrite" in kwargs["data"]["scope"]


@pytest.mark.asyncio
async def test_refresh_google_token_uses_refresh_grant(with_fernet_key):
    fake_response = AsyncMock()
    fake_response.raise_for_status = lambda: None
    fake_response.json = lambda: {"access_token": "newAT"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await oauth.refresh_google_token("RT-123")

    _, kwargs = mock_client.post.call_args
    assert kwargs["data"]["grant_type"] == "refresh_token"
    assert kwargs["data"]["refresh_token"] == "RT-123"
