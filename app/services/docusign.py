"""DocuSign e-signature integration.

Auth: JWT-grant (server-side, no per-user OAuth dialog).
Flow:
  1. obtain access token via JWT grant (cached for ~1h)
  2. POST /restapi/v2.1/accounts/{account_id}/envelopes
     with PDF document + recipient
  3. user signs in DocuSign UI (URL returned in `signing_url`)
  4. webhook (configured separately) hits us when status changes

This module exposes the *minimum* surface needed by the offer-sending
flow:
- get_access_token()
- send_envelope_for_offer(offer, candidate, pdf_bytes) → envelope_id, signing_url
- get_envelope_status(envelope_id) → 'sent' | 'delivered' | 'completed' | 'declined' | 'voided'

If DOCUSIGN_INTEGRATION_KEY is not configured, every helper raises
DocuSignNotConfigured so the caller can fall back to a manual flow
(email PDF → recruiter sends from DocuSign UI).
"""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt as pyjwt  # python-jose ships PyJWT-compatible API

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class DocuSignError(Exception):
    pass


class DocuSignNotConfigured(DocuSignError):
    pass


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float  # epoch seconds


_token_cache: _CachedToken | None = None


def _check_configured() -> None:
    s = get_settings()
    missing = [
        name for name in (
            "DOCUSIGN_INTEGRATION_KEY",
            "DOCUSIGN_USER_ID",
            "DOCUSIGN_ACCOUNT_ID",
            "DOCUSIGN_PRIVATE_KEY",
        )
        if not getattr(s, name, "")
    ]
    if missing:
        raise DocuSignNotConfigured(
            f"DocuSign disabled — missing settings: {', '.join(missing)}"
        )


def _build_jwt() -> str:
    """Build the JWT used to obtain a DocuSign access token (RS256, 1h TTL)."""
    s = get_settings()
    now = int(time.time())
    claims = {
        "iss": s.DOCUSIGN_INTEGRATION_KEY,
        "sub": s.DOCUSIGN_USER_ID,
        "aud": s.DOCUSIGN_AUTH_HOST,  # account-d.docusign.com (demo) or account.docusign.com
        "iat": now,
        "exp": now + 3600,
        "scope": "signature impersonation",
    }
    return pyjwt.encode(claims, s.DOCUSIGN_PRIVATE_KEY, algorithm="RS256")


def get_access_token() -> str:
    """Obtain (and cache) an access token via the JWT grant flow.

    Cached for ~50 minutes (10-min safety margin under the 1h TTL).
    """
    global _token_cache
    _check_configured()
    if _token_cache and _token_cache.expires_at > time.time() + 60:
        return _token_cache.access_token

    s = get_settings()
    assertion = _build_jwt()
    with httpx.Client(timeout=10.0) as client:
        r = client.post(
            f"https://{s.DOCUSIGN_AUTH_HOST}/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
    if r.status_code != 200:
        raise DocuSignError(f"token exchange failed: {r.status_code} {r.text[:200]}")
    body = r.json()
    _token_cache = _CachedToken(
        access_token=body["access_token"],
        expires_at=time.time() + int(body.get("expires_in", 3000)),
    )
    return _token_cache.access_token


def _api_base() -> str:
    s = get_settings()
    return f"https://{s.DOCUSIGN_API_HOST}/restapi/v2.1/accounts/{s.DOCUSIGN_ACCOUNT_ID}"


def send_envelope_for_offer(
    *,
    candidate_name: str,
    candidate_email: str,
    position_title: str,
    pdf_bytes: bytes,
) -> dict[str, Any]:
    """Send a one-recipient envelope. Returns the DocuSign API response
    (containing envelope_id, status, uri)."""
    token = get_access_token()
    pdf_b64 = base64.b64encode(pdf_bytes).decode()
    payload = {
        "emailSubject": f"Your offer for {position_title}",
        "documents": [{
            "documentBase64": pdf_b64,
            "name": "offer.pdf",
            "fileExtension": "pdf",
            "documentId": "1",
        }],
        "recipients": {
            "signers": [{
                "email": candidate_email,
                "name": candidate_name,
                "recipientId": "1",
                "routingOrder": "1",
                "tabs": {
                    # Anchor-based: the PDF should contain the literal "/sig1/" tag
                    # at the position where the signature must go.
                    "signHereTabs": [{
                        "anchorString": "/sig1/",
                        "anchorXOffset": "0",
                        "anchorYOffset": "0",
                        "anchorUnits": "pixels",
                    }],
                },
            }],
        },
        "status": "sent",  # 'created' = draft, 'sent' = email goes out immediately
    }
    with httpx.Client(timeout=15.0) as client:
        r = client.post(
            f"{_api_base()}/envelopes",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    if r.status_code not in (200, 201):
        raise DocuSignError(f"envelope create failed: {r.status_code} {r.text[:300]}")
    return r.json()


def get_envelope_status(envelope_id: str) -> str:
    """Poll an envelope's status. Webhook-based updates are preferred but
    this helper exists for reconciliation / admin dashboards."""
    token = get_access_token()
    with httpx.Client(timeout=10.0) as client:
        r = client.get(
            f"{_api_base()}/envelopes/{envelope_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        raise DocuSignError(f"envelope status failed: {r.status_code} {r.text[:200]}")
    return r.json().get("status", "unknown")
