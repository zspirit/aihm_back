from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.rate_limit import limiter

logger = structlog.get_logger()
settings = get_settings()

# --- Sentry ---
if settings.SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        send_default_pii=False,
    )
    logger.info("sentry_initialized", environment=settings.SENTRY_ENVIRONMENT)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_startup", version="0.1.0")
    yield
    logger.info("app_shutdown")


app = FastAPI(
    title="AIHM API",
    description="AI Hiring Manager - API de pre-screening telephonique par IA",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# --- Security Headers Middleware ---
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not settings.DEBUG:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"connect-src 'self' {settings.FRONTEND_URL} https://*.sentry.io; "
                "img-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; "
                "frame-ancestors 'none'"
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from app.api.v1.analytics import router as analytics_router
from app.api.v1.auth import router as auth_router
from app.api.v1.candidates import router as candidates_router
from app.api.v1.consent import router as consent_router
from app.api.v1.copilot import router as copilot_router
from app.api.v1.interviews import router as interviews_router
from app.api.v1.positions import router as positions_router
from app.api.v1.webhooks import router as webhooks_router
from app.api.v1.webhooks_config import router as webhooks_config_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.bulk_import import router as bulk_import_router
from app.api.v1.matching import router as matching_router
from app.api.v1.reports import router as reports_router

app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(positions_router, prefix=settings.API_V1_PREFIX)
app.include_router(candidates_router, prefix=settings.API_V1_PREFIX)
app.include_router(interviews_router, prefix=settings.API_V1_PREFIX)
app.include_router(consent_router, prefix=settings.API_V1_PREFIX)
app.include_router(webhooks_router, prefix=settings.API_V1_PREFIX)
app.include_router(webhooks_config_router, prefix=settings.API_V1_PREFIX)
app.include_router(analytics_router, prefix=settings.API_V1_PREFIX)
app.include_router(copilot_router, prefix=settings.API_V1_PREFIX)
app.include_router(notifications_router, prefix=settings.API_V1_PREFIX)
app.include_router(bulk_import_router, prefix=settings.API_V1_PREFIX)
app.include_router(matching_router, prefix=settings.API_V1_PREFIX)
app.include_router(reports_router, prefix=settings.API_V1_PREFIX)


# --- Health Check enrichi ---
@app.get("/health")
async def health():
    checks = {"version": "0.1.0"}

    # PostgreSQL
    try:
        from sqlalchemy import text

        from app.core.database import async_session

        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    # Redis
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # MinIO
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{settings.S3_ENDPOINT}/minio/health/live", timeout=3)
            checks["minio"] = "ok" if resp.status_code == 200 else f"status: {resp.status_code}"
    except Exception as e:
        checks["minio"] = f"error: {e}"

    all_ok = all(v == "ok" for k, v in checks.items() if k != "version")
    checks["status"] = "ok" if all_ok else "degraded"

    return checks
