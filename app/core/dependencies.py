from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User

VALID_ROLES = ("admin", "recruiter", "viewer")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expire",
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide")

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable",
        )

    return user


def get_tenant_id(current_user: User = Depends(get_current_user)) -> UUID:
    return current_user.tenant_id


def require_role(*allowed_roles: str):
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' non autorise. "
                f"Roles requis: {', '.join(allowed_roles)}",
            )
        return current_user

    return dependency


FREE_TIER_MONTHLY_LIMIT = 3


async def check_free_tier_limit(db: AsyncSession, tenant_id: UUID) -> None:
    """Raise HTTP 402 if the tenant is on the free plan and has reached the monthly interview limit."""
    from app.models.interview import Interview
    from app.models.tenant import Tenant

    tenant = await db.get(Tenant, tenant_id)
    if not tenant or tenant.plan != "free":
        return  # Paid plan or unknown tenant — no limit

    now = datetime.now(timezone.utc)
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    count = await db.scalar(
        select(func.count(Interview.id))
        .where(Interview.tenant_id == tenant_id)
        .where(Interview.created_at >= first_of_month)
    )

    if count >= FREE_TIER_MONTHLY_LIMIT:
        raise HTTPException(
            status_code=402,
            detail="Limite du plan gratuit atteinte (3 entretiens/mois). Passez au plan Pro.",
        )


def require_module(module_key: str):
    """
    Dependency: vérifie que le module est activé pour ce tenant.
    Lève HTTP 403 si le module est désactivé.

    Défaut: tous les modules sont activés par défaut (opt-out model).
    """
    async def _check(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> None:
        from app.models.tenant import Tenant

        tenant = await db.get(Tenant, current_user.tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        modules = tenant.modules_config or {}
        # Default True: if module_key not in dict, it's enabled
        is_enabled = modules.get(module_key, True)

        if not is_enabled:
            raise HTTPException(
                status_code=403,
                detail=f"Le module '{module_key}' est désactivé pour votre compte. Contactez votre administrateur.",
            )

    return Depends(_check)
