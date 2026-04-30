from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "AIHM"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://aihm:aihm@localhost:5432/aihm"
    DATABASE_ECHO: bool = False

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # MinIO / S3
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_EXTERNAL_ENDPOINT: str = ""
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_CVS: str = "cvs"
    S3_BUCKET_REPORTS: str = "reports"
    S3_BUCKET_AUDIO: str = "audio"

    # Anthropic
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5-20250929"

    # Twilio
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    TWILIO_WEBHOOK_BASE_URL: str = "https://example.com"

    # Email (Resend)
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@aihm.ai"

    # Whisper (base instead of large-v3 to fit in 3.7GB RAM server)
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"

    # TTS (Conversation)
    TTS_VOICE: str = "fr-FR-HenriNeural"
    TTS_BUCKET: str = "tts-audio"
    TTS_PRESIGNED_URL_EXPIRY: int = 7200
    TTS_RATE: str = "-5%"

    # Safety Classifier (Conversation)
    SAFETY_MODEL: str = "claude-haiku-4-5-20251001"
    SAFETY_MAX_TOKENS: int = 100

    # Conversation Settings
    CONVERSATION_MAX_RETRIES: int = 2
    CONVERSATION_GATHER_TIMEOUT: int = 5

    # Sentry
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"

    # Calendar OAuth (Phase 4.2)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    OAUTH_REDIRECT_BASE_URL: str = "http://localhost:5173"  # frontend route handles callback
    # Fernet key for at-rest encryption of OAuth tokens.
    # Generate via: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Empty in dev → tokens stored in plaintext (NEVER do this in prod).
    ENCRYPTION_KEY: str = ""

    # DocuSign e-signature (Phase 4.6) — JWT grant flow
    DOCUSIGN_INTEGRATION_KEY: str = ""
    DOCUSIGN_USER_ID: str = ""
    DOCUSIGN_ACCOUNT_ID: str = ""
    DOCUSIGN_PRIVATE_KEY: str = ""
    DOCUSIGN_AUTH_HOST: str = "account-d.docusign.com"  # demo; prod = account.docusign.com
    DOCUSIGN_API_HOST: str = "demo.docusign.net"        # demo; prod = www.docusign.net

    # App
    FRONTEND_URL: str = "http://localhost:5173"  # Override via env var on prod
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://localhost:5176", "http://localhost:5177", "http://localhost:5178", "http://localhost:5179", "http://localhost:3000", "http://89.167.78.19:3000"]
    MAX_CV_SIZE_MB: int = 10
    MAX_INTERVIEW_DURATION_SECONDS: int = 600
    DEFAULT_DATA_RETENTION_DAYS: int = 180

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
