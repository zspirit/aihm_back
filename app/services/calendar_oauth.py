"""Calendar OAuth helpers — Google Calendar + Microsoft Outlook.

Real OAuth2 flow:
1. /authorize → returns Google/MS auth URL with a signed state token (CSRF guard)
2. user is redirected back with `code` + `state`
3. /callback → verify state, exchange code for tokens, store encrypted in
   user_integrations (one row per (user_id, provider))

State token: HMAC-signed JSON containing {user_id, provider, nonce, ts}.
Verified within 10 minutes of issuance to prevent replay.

Tokens at rest: Fernet-encrypted using settings.ENCRYPTION_KEY. If the key
is empty (dev only), tokens are stored as-is — never deploy without the
key set.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

# OAuth provider endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]

MICROSOFT_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MICROSOFT_SCOPES = ["Calendars.ReadWrite", "offline_access"]

# Internal provider names matching UserIntegration.provider
PROVIDER_GOOGLE = "google_calendar"
PROVIDER_MICROSOFT = "microsoft_calendar"

STATE_TTL_SECONDS = 600  # 10 min — long enough for slow OAuth dialogs, short enough to limit replay


# ─── Encryption ───────────────────────────────────────────────────────────────


def _fernet() -> Fernet | None:
    """Return a Fernet instance, or None if no key is configured (dev only)."""
    key = get_settings().ENCRYPTION_KEY
    if not key:
        return None
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(token: str) -> str:
    """Encrypt an OAuth token. Returns the original token if no key is set
    (dev mode). Caller is responsible for not deploying without a key."""
    f = _fernet()
    if f is None:
        return token
    return f.encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt an OAuth token. If no key is set, returns the input as-is."""
    f = _fernet()
    if f is None:
        return encrypted
    try:
        return f.decrypt(encrypted.encode()).decode()
    except InvalidToken as e:
        raise ValueError("token decryption failed — wrong key or tampered ciphertext") from e


# ─── State token (CSRF) ───────────────────────────────────────────────────────


def _hmac_sign(message: bytes) -> str:
    secret = get_settings().JWT_SECRET_KEY.encode()
    digest = hmac.new(secret, message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_state(user_id: str, provider: str) -> str:
    """Generate a signed state token: <payload>.<sig>."""
    payload = {
        "user_id": str(user_id),
        "provider": provider,
        "nonce": secrets.token_urlsafe(16),
        "ts": int(time.time()),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    encoded = _b64url_encode(raw)
    sig = _hmac_sign(encoded.encode())
    return f"{encoded}.{sig}"


def verify_state(state: str, expected_user_id: str, expected_provider: str) -> bool:
    """Validate state token: signature + TTL + user/provider match.

    Returns True only if every check passes. Never raise — return False so
    the caller can return a clean 400 to the OAuth flow.
    """
    try:
        encoded, sig = state.rsplit(".", 1)
    except ValueError:
        return False

    expected_sig = _hmac_sign(encoded.encode())
    if not hmac.compare_digest(sig, expected_sig):
        return False

    try:
        payload = json.loads(_b64url_decode(encoded))
    except (ValueError, json.JSONDecodeError):
        return False

    if payload.get("user_id") != str(expected_user_id):
        return False
    if payload.get("provider") != expected_provider:
        return False

    ts = payload.get("ts", 0)
    if not isinstance(ts, int) or time.time() - ts > STATE_TTL_SECONDS:
        return False

    return True


# ─── URL builders ─────────────────────────────────────────────────────────────


def _redirect_uri(provider: str) -> str:
    base = get_settings().OAUTH_REDIRECT_BASE_URL.rstrip("/")
    # Frontend handles the callback page and POSTs (code, state) back to our API
    return f"{base}/integrations/{provider}/callback"


def build_google_authorize_url(user_id: str) -> str:
    s = get_settings()
    if not s.GOOGLE_CLIENT_ID:
        raise RuntimeError("GOOGLE_CLIENT_ID not configured")
    state = make_state(user_id, PROVIDER_GOOGLE)
    params = {
        "client_id": s.GOOGLE_CLIENT_ID,
        "redirect_uri": _redirect_uri("google"),
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",  # required for refresh_token
        "prompt": "consent",  # force refresh_token issuance even on re-auth
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def build_microsoft_authorize_url(user_id: str) -> str:
    s = get_settings()
    if not s.MICROSOFT_CLIENT_ID:
        raise RuntimeError("MICROSOFT_CLIENT_ID not configured")
    state = make_state(user_id, PROVIDER_MICROSOFT)
    params = {
        "client_id": s.MICROSOFT_CLIENT_ID,
        "redirect_uri": _redirect_uri("outlook"),
        "response_type": "code",
        "scope": " ".join(MICROSOFT_SCOPES),
        "response_mode": "query",
        "state": state,
    }
    return f"{MICROSOFT_AUTH_URL}?{urlencode(params)}"


# ─── Token exchange ───────────────────────────────────────────────────────────


async def exchange_google_code(code: str) -> dict[str, Any]:
    s = get_settings()
    payload = {
        "code": code,
        "client_id": s.GOOGLE_CLIENT_ID,
        "client_secret": s.GOOGLE_CLIENT_SECRET,
        "redirect_uri": _redirect_uri("google"),
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(GOOGLE_TOKEN_URL, data=payload)
    r.raise_for_status()
    return r.json()


async def exchange_microsoft_code(code: str) -> dict[str, Any]:
    s = get_settings()
    payload = {
        "code": code,
        "client_id": s.MICROSOFT_CLIENT_ID,
        "client_secret": s.MICROSOFT_CLIENT_SECRET,
        "redirect_uri": _redirect_uri("outlook"),
        "grant_type": "authorization_code",
        "scope": " ".join(MICROSOFT_SCOPES),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(MICROSOFT_TOKEN_URL, data=payload)
    r.raise_for_status()
    return r.json()


async def refresh_google_token(refresh_token: str) -> dict[str, Any]:
    s = get_settings()
    payload = {
        "refresh_token": refresh_token,
        "client_id": s.GOOGLE_CLIENT_ID,
        "client_secret": s.GOOGLE_CLIENT_SECRET,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(GOOGLE_TOKEN_URL, data=payload)
    r.raise_for_status()
    return r.json()


async def refresh_microsoft_token(refresh_token: str) -> dict[str, Any]:
    s = get_settings()
    payload = {
        "refresh_token": refresh_token,
        "client_id": s.MICROSOFT_CLIENT_ID,
        "client_secret": s.MICROSOFT_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "scope": " ".join(MICROSOFT_SCOPES),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(MICROSOFT_TOKEN_URL, data=payload)
    r.raise_for_status()
    return r.json()
