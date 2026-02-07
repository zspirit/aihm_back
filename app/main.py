from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="AIHM API",
    description="AI Hiring Manager - API de pre-screening telephonique par IA",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from app.api.v1.auth import router as auth_router
from app.api.v1.candidates import router as candidates_router
from app.api.v1.consent import router as consent_router
from app.api.v1.interviews import router as interviews_router
from app.api.v1.positions import router as positions_router
from app.api.v1.webhooks import router as webhooks_router

app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(positions_router, prefix=settings.API_V1_PREFIX)
app.include_router(candidates_router, prefix=settings.API_V1_PREFIX)
app.include_router(interviews_router, prefix=settings.API_V1_PREFIX)
app.include_router(consent_router, prefix=settings.API_V1_PREFIX)
app.include_router(webhooks_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
