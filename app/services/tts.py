"""TTS provider adapter — multi-backend abstraction.

Permet de swap entre edge-tts (Microsoft Edge Read Aloud, gratuit), OpenAI TTS
(nova FR, ~$0.03/interview) et ElevenLabs Turbo v2.5 (Charlie/Antoine FR,
~$0.10/interview) via la variable d'environnement `TTS_PROVIDER`.

Sélection runtime :
    settings.TTS_PROVIDER in {"edge", "openai", "elevenlabs"}

Chaque provider implémente `TTSProvider.synthesize(text, voice, rate) -> bytes`
qui retourne un MP3 prêt à uploader sur MinIO.

Voir `design-review/VOICE_BASELINE.md` pour le contexte architecture +
décisions de refonte voice IA (release v1.0, ticket VOICE-02).
"""
from __future__ import annotations

import asyncio
import io
import os
from abc import ABC, abstractmethod
from typing import Optional

import structlog

from app.core.config import get_settings

logger = structlog.get_logger()


# ─── Default voices per provider ────────────────────────────────────────────
# Mapping logique : "default FR" → identifiant spécifique provider.
# Permet de basculer de provider sans renommer le code applicatif.
DEFAULT_VOICE_BY_PROVIDER: dict[str, str] = {
    "edge": "fr-FR-HenriNeural",          # Microsoft Edge Read Aloud (gratuit)
    "openai": "nova",                      # OpenAI tts-1 — meilleure voix FR
    "elevenlabs": "IKne3meq5aSn9XLyUdCD",  # ElevenLabs "Charlie" multilingual
}


# ─── Interface ─────────────────────────────────────────────────────────────

class TTSProvider(ABC):
    """Interface abstraite pour un provider TTS."""

    name: str  # identifiant ("edge", "openai", "elevenlabs")

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: str = "-5%",
    ) -> bytes:
        """Génère un MP3 depuis du texte.

        Args:
            text: texte à synthétiser (FR).
            voice: identifiant voix spécifique au provider. Si None, utilise
                le default mappé dans `DEFAULT_VOICE_BY_PROVIDER`.
            rate: vitesse de speech (format provider-specific ; ignoré si non
                applicable).

        Returns:
            MP3 bytes prêts pour upload S3/MinIO.

        Raises:
            TTSError: si la génération échoue. Le caller doit catch et fallback
                vers un autre provider ou loguer + remonter.
        """
        ...


class TTSError(Exception):
    """Erreur de synthèse TTS. Chaque adapter wrap ses exceptions natives."""


# ─── Adapter 1: edge-tts (Microsoft Edge Read Aloud, gratuit) ───────────────

class EdgeTTSProvider(TTSProvider):
    """edge-tts est la lib non-officielle qui utilise les voix Edge Read Aloud.
    Gratuit, aucune clé API requise. Qualité correcte (~3.5/5 MOS) mais voix
    monotone par rapport aux providers neuraux récents. Conservé en fallback
    et pour les environnements offline-friendly."""

    name = "edge"

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: str = "-5%",
    ) -> bytes:
        import edge_tts  # import local : la lib peut être absente si provider non utilisé

        voice = voice or DEFAULT_VOICE_BY_PROVIDER["edge"]
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        buf = io.BytesIO()
        try:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
        except Exception as exc:
            logger.error("tts_edge_error", text_len=len(text), voice=voice, error=str(exc))
            raise TTSError(f"edge-tts failed: {exc}") from exc
        buf.seek(0)
        return buf.read()


# ─── Adapter 2: OpenAI TTS (nova FR, $0.015/1K chars sur tts-1) ─────────────

class OpenAITTSProvider(TTSProvider):
    """OpenAI tts-1 / tts-1-hd / gpt-4o-mini-tts. Voix `nova` est la meilleure
    en français selon nos tests. Pricing 2026 : $15/1M chars (tts-1) ou
    $30/1M (tts-1-hd). Coût par interview 5min ~$0.03 (tts-1) ou ~$0.06 (hd).

    Requiert `OPENAI_API_KEY` dans l'environnement. Si absent, raise au premier
    appel (pas au constructor → fail-fast logique).
    """

    name = "openai"

    def __init__(self, model: str = "tts-1") -> None:
        self.model = model  # "tts-1" | "tts-1-hd" | "gpt-4o-mini-tts"

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: str = "-5%",
    ) -> bytes:
        import httpx

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise TTSError("OPENAI_API_KEY missing — cannot use OpenAITTSProvider")

        voice = voice or DEFAULT_VOICE_BY_PROVIDER["openai"]
        # OpenAI TTS `speed` accepte float 0.25-4.0 (1.0 = normal). On convertit
        # un rate de la forme "-5%" en 0.95 pour matcher l'UX edge-tts.
        try:
            speed = 1.0 + (float(rate.rstrip("%")) / 100.0) if "%" in rate else 1.0
        except ValueError:
            speed = 1.0
        speed = max(0.5, min(2.0, speed))  # clamp safety

        payload = {
            "model": self.model,
            "voice": voice,
            "input": text,
            "response_format": "mp3",
            "speed": speed,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                return resp.content
        except httpx.HTTPError as exc:
            logger.error(
                "tts_openai_error",
                text_len=len(text),
                voice=voice,
                model=self.model,
                error=str(exc),
            )
            raise TTSError(f"OpenAI TTS failed: {exc}") from exc


# ─── Adapter 3: ElevenLabs (Turbo v2.5, ~$0.10/interview 5min) ──────────────

class ElevenLabsTTSProvider(TTSProvider):
    """ElevenLabs Turbo v2.5 multilingual. Voix Charlie (`IKne3meq5aSn9XLyUdCD`)
    et Antoine recommandées pour le FR. Pricing variable selon plan ; à volume
    test (~200 entretiens/mois) : Free tier 10K chars/mois gratuits suffit pour
    démarrer, sinon Creator $22/mo pour 100K chars.

    Requiert `ELEVENLABS_API_KEY`. Stream API en POST pour latence minimale.
    """

    name = "elevenlabs"

    def __init__(self, model_id: str = "eleven_turbo_v2_5") -> None:
        self.model_id = model_id

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: str = "-5%",
    ) -> bytes:
        import httpx

        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            raise TTSError("ELEVENLABS_API_KEY missing — cannot use ElevenLabsTTSProvider")

        voice = voice or DEFAULT_VOICE_BY_PROVIDER["elevenlabs"]

        # ElevenLabs ne supporte pas de `rate` direct ; le speech speed se
        # gère via les voice_settings (stability + similarity_boost). On garde
        # un default conservateur pour ne pas surprendre l'auditeur.
        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                    headers={
                        "xi-api-key": api_key,
                        "Accept": "audio/mpeg",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                return resp.content
        except httpx.HTTPError as exc:
            logger.error(
                "tts_elevenlabs_error",
                text_len=len(text),
                voice=voice,
                model_id=self.model_id,
                error=str(exc),
            )
            raise TTSError(f"ElevenLabs TTS failed: {exc}") from exc


# ─── Factory ───────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, type[TTSProvider]] = {
    "edge": EdgeTTSProvider,
    "openai": OpenAITTSProvider,
    "elevenlabs": ElevenLabsTTSProvider,
}


def get_tts_provider(name: Optional[str] = None) -> TTSProvider:
    """Retourne le provider configuré.

    Si `name` est fourni, utilise ce provider explicitement (utile pour A/B test).
    Sinon, utilise `settings.TTS_PROVIDER` (default "edge" pour rétro-compat).

    Raises:
        ValueError: si le nom du provider est inconnu.
    """
    if name is None:
        settings = get_settings()
        name = getattr(settings, "TTS_PROVIDER", "edge")

    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown TTS_PROVIDER '{name}'. Valid: {list(_PROVIDERS.keys())}"
        )
    return cls()


async def synthesize(
    text: str,
    voice: Optional[str] = None,
    rate: str = "-5%",
    provider: Optional[str] = None,
) -> bytes:
    """Helper sync-style : génère un MP3 avec le provider configuré (ou
    explicite via `provider`). Wrap la sélection + l'appel async en 1 ligne
    pour les callers qui veulent juste "donne-moi le MP3"."""
    p = get_tts_provider(provider)
    logger.info("tts_synthesize_start", provider=p.name, text_len=len(text), voice=voice)
    audio = await p.synthesize(text=text, voice=voice, rate=rate)
    logger.info(
        "tts_synthesize_done",
        provider=p.name,
        text_len=len(text),
        audio_bytes=len(audio),
    )
    return audio


# ─── A/B test utility (VOICE-03c) ───────────────────────────────────────────

async def synthesize_all_providers(
    text: str,
    voice_overrides: Optional[dict[str, str]] = None,
) -> dict[str, bytes]:
    """Génère le même texte avec TOUS les providers configurables.

    Utilisé par VOICE-03c pour A/B test : générer la même phrase via edge /
    openai / elevenlabs, sauvegarder les 3 MP3 et écouter pour décider.

    Skip silencieusement les providers dont la clé API est absente
    (ex: pas d'OPENAI_API_KEY → on génère juste edge + elevenlabs).
    """
    voice_overrides = voice_overrides or {}
    results: dict[str, bytes] = {}
    for name in _PROVIDERS:
        try:
            voice = voice_overrides.get(name)
            audio = await synthesize(text, voice=voice, provider=name)
            results[name] = audio
        except TTSError as exc:
            logger.warning("tts_provider_skipped", provider=name, reason=str(exc))
        except Exception as exc:
            logger.error("tts_provider_unexpected_error", provider=name, error=str(exc))
    return results
