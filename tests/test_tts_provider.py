"""Tests for the TTS provider adapter (back/app/services/tts.py).

Couvre :
- Factory `get_tts_provider` : valid/invalid names, default from settings
- Sélection via env var `TTS_PROVIDER`
- OpenAI provider : raise TTSError if `OPENAI_API_KEY` missing
- ElevenLabs provider : raise TTSError if `ELEVENLABS_API_KEY` missing
- Speed conversion ("-5%" → 0.95) pour OpenAI
- Edge provider : génération réelle (lib edge-tts est offline-friendly, pas
  d'API call externe)

Note : on ne teste pas la qualité audio (impossible sans écoute humaine),
seulement les contrats d'interface.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.services import tts as tts_module
from app.services.tts import (
    DEFAULT_VOICE_BY_PROVIDER,
    EdgeTTSProvider,
    ElevenLabsTTSProvider,
    OpenAITTSProvider,
    TTSError,
    get_tts_provider,
)


# ─── Factory ───────────────────────────────────────────────────────────────


def test_factory_returns_edge_by_default(monkeypatch):
    """Si `settings.TTS_PROVIDER` n'est pas défini, default = edge (rétro-compat)."""
    monkeypatch.delenv("TTS_PROVIDER", raising=False)
    # On clear le settings cache pour qu'il recharge
    tts_module.get_settings.cache_clear()
    provider = get_tts_provider()
    assert provider.name == "edge"


def test_factory_explicit_name():
    assert get_tts_provider("edge").name == "edge"
    assert get_tts_provider("openai").name == "openai"
    assert get_tts_provider("elevenlabs").name == "elevenlabs"


def test_factory_invalid_name_raises():
    with pytest.raises(ValueError, match="Unknown TTS_PROVIDER"):
        get_tts_provider("nonexistent")


def test_factory_reads_settings_when_no_arg(monkeypatch):
    monkeypatch.setenv("TTS_PROVIDER", "openai")
    tts_module.get_settings.cache_clear()
    provider = get_tts_provider()
    assert provider.name == "openai"


# ─── Default voices ────────────────────────────────────────────────────────


def test_default_voice_mapping_complete():
    """Chaque provider doit avoir une voix par défaut configurée."""
    for name in ("edge", "openai", "elevenlabs"):
        assert name in DEFAULT_VOICE_BY_PROVIDER
        assert DEFAULT_VOICE_BY_PROVIDER[name], f"voice empty for {name}"


# ─── OpenAI provider ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_raises_without_api_key(monkeypatch):
    """Si OPENAI_API_KEY absent, raise TTSError au runtime (pas au construct)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAITTSProvider()
    with pytest.raises(TTSError, match="OPENAI_API_KEY missing"):
        await provider.synthesize("Bonjour", voice="nova")


@pytest.mark.asyncio
async def test_openai_speed_conversion(monkeypatch):
    """`rate='-5%'` doit produire speed=0.95 dans le payload OpenAI."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    provider = OpenAITTSProvider()
    captured: dict = {}

    class _FakeResponse:
        content = b"\xff\xfbfake mp3 bytes"

        def raise_for_status(self):
            pass

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        await provider.synthesize("Bonjour", voice="nova", rate="-5%")

    assert captured["json"]["speed"] == pytest.approx(0.95)
    assert captured["json"]["voice"] == "nova"
    assert captured["json"]["input"] == "Bonjour"


@pytest.mark.asyncio
async def test_openai_speed_clamp(monkeypatch):
    """Rate hors-limites doit être clampé (0.5 ≤ speed ≤ 2.0)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    provider = OpenAITTSProvider()
    captured: dict = {}

    class _FakeResponse:
        content = b"\xff\xfbfake"

        def raise_for_status(self):
            pass

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, headers=None, json=None):
            captured["json"] = json
            return _FakeResponse()

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        await provider.synthesize("X", rate="+500%")  # would be 6.0, must clamp to 2.0
    assert captured["json"]["speed"] == 2.0


# ─── ElevenLabs provider ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_elevenlabs_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    provider = ElevenLabsTTSProvider()
    with pytest.raises(TTSError, match="ELEVENLABS_API_KEY missing"):
        await provider.synthesize("Bonjour")


@pytest.mark.asyncio
async def test_elevenlabs_default_voice(monkeypatch):
    """Si voice=None, utilise la voix Charlie par défaut."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test-fake")
    provider = ElevenLabsTTSProvider()
    captured: dict = {}

    class _FakeResponse:
        content = b"\xff\xfbfake"

        def raise_for_status(self):
            pass

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            return _FakeResponse()

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        await provider.synthesize("Bonjour", voice=None)

    # default voice ID Charlie présent dans l'URL
    assert DEFAULT_VOICE_BY_PROVIDER["elevenlabs"] in captured["url"]


# ─── Edge provider (lib offline) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_edge_synthesize_basic():
    """edge-tts ne nécessite pas d'API key (utilise les endpoints Edge Read
    Aloud non authentifiés). Test génération basique."""
    provider = EdgeTTSProvider()
    audio = await provider.synthesize("Bonjour test", voice=None, rate="-5%")
    # MP3 bytes : magic header commence par ID3 ou frame sync (0xff 0xfb/0xfa)
    assert len(audio) > 100
    assert audio[:3] == b"ID3" or audio[0] == 0xFF
