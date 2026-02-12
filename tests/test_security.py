"""Tests for security utilities (no DB needed)."""

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password():
    hashed = hash_password("mysecret")
    assert hashed != "mysecret"
    assert verify_password("mysecret", hashed)
    assert not verify_password("wrongpass", hashed)


def test_create_and_decode_access_token():
    data = {"sub": "user-123", "tenant_id": "tenant-456", "role": "admin"}
    token = create_access_token(data)
    payload = decode_token(token)

    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["tenant_id"] == "tenant-456"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token():
    data = {"sub": "user-789", "tenant_id": "tenant-012", "role": "recruiter"}
    token = create_refresh_token(data)
    payload = decode_token(token)

    assert payload is not None
    assert payload["type"] == "refresh"
    assert payload["sub"] == "user-789"


def test_decode_invalid_token():
    payload = decode_token("invalid.token.value")
    assert payload is None


def test_decode_empty_token():
    payload = decode_token("")
    assert payload is None
