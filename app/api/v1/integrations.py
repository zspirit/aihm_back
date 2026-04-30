"""External integrations admin endpoints (Phase 4.6).

- Slack: per-tenant webhook URL stored in tenant.modules_config.
  GET    /integrations/slack          → current webhook URL (or null)
  PUT    /integrations/slack          → set/replace
  DELETE /integrations/slack          → remove
  POST   /integrations/slack/test     → send a 'hello' message
- DocuSign: server-wide config (env vars), no per-tenant settings.
  GET  /integrations/docusign         → configured? (boolean)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_db, require_role
from app.models.tenant import Tenant
from app.models.user import User
from app.services import slack as slack_svc

router = APIRouter(prefix="/integrations", tags=["integrations"])

_SLACK_KEY = "slack_webhook_url"


# ─── Slack ────────────────────────────────────────────────────────────────────


class SlackConfig(BaseModel):
    webhook_url: str | None = None


class SlackUpdate(BaseModel):
    webhook_url: str = Field(..., pattern=r"^https://hooks\.slack\.com/services/.+")


async def _get_tenant(db: AsyncSession, tenant_id) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        # Authenticated user with a deleted tenant — treat as 404 to avoid
        # leaking the underlying state.
        raise HTTPException(status_code=404, detail="tenant not found")
    return tenant


@router.get("/slack", response_model=SlackConfig)
async def get_slack_config(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _get_tenant(db, current_user.tenant_id)
    config = tenant.modules_config or {}
    return SlackConfig(webhook_url=config.get(_SLACK_KEY))


@router.put("/slack", response_model=SlackConfig)
async def set_slack_config(
    payload: SlackUpdate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _get_tenant(db, current_user.tenant_id)
    config = dict(tenant.modules_config or {})
    config[_SLACK_KEY] = payload.webhook_url
    tenant.modules_config = config
    await db.commit()
    return SlackConfig(webhook_url=payload.webhook_url)


@router.delete("/slack", response_model=SlackConfig)
async def delete_slack_config(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _get_tenant(db, current_user.tenant_id)
    config = dict(tenant.modules_config or {})
    config.pop(_SLACK_KEY, None)
    tenant.modules_config = config
    await db.commit()
    return SlackConfig(webhook_url=None)


@router.post("/slack/test")
async def test_slack(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _get_tenant(db, current_user.tenant_id)
    url = (tenant.modules_config or {}).get(_SLACK_KEY)
    if not url:
        raise HTTPException(status_code=400, detail="Slack not configured")
    try:
        await slack_svc.send_message_strict(
            url,
            f":wave: Hello from AIHM — integration test from *{tenant.name}*",
        )
    except slack_svc.SlackError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"status": "ok", "message": "test sent"}


# ─── DocuSign ─────────────────────────────────────────────────────────────────


class DocuSignStatus(BaseModel):
    configured: bool
    account_id: str | None = None
    auth_host: str
    api_host: str


@router.get("/docusign", response_model=DocuSignStatus)
async def get_docusign_status(
    _current_user: User = Depends(require_role("admin")),
):
    s = get_settings()
    configured = bool(
        s.DOCUSIGN_INTEGRATION_KEY
        and s.DOCUSIGN_USER_ID
        and s.DOCUSIGN_ACCOUNT_ID
        and s.DOCUSIGN_PRIVATE_KEY
    )
    return DocuSignStatus(
        configured=configured,
        account_id=s.DOCUSIGN_ACCOUNT_ID or None,
        auth_host=s.DOCUSIGN_AUTH_HOST,
        api_host=s.DOCUSIGN_API_HOST,
    )
