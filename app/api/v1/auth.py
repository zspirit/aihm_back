import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import VALID_ROLES, get_current_user, require_role
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.audit_log import AuditLog
from app.models.email_verification_token import EmailVerificationToken
from app.models.password_reset_token import PasswordResetToken
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    InviteUserRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.services.audit import log_action
from app.services.email import render as render_email
from app.workers.notifications import send_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(request: Request, data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email deja utilise")

    tenant = Tenant(name=data.company_name)
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role="admin",
        email_verified=False,
    )
    db.add(user)
    await db.flush()

    # Create email verification token
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    verification_token = EmailVerificationToken(
        user_id=user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(verification_token)
    await db.flush()

    # Send verification email
    verify_url = f"{settings.FRONTEND_URL}/verify-email/{token}"
    html = render_email(
        "email/email_verification.html",
        user_name=user.full_name,
        verify_url=verify_url,
        tenant_name=tenant.name,
    )
    send_email.delay(user.email, "Verifiez votre adresse email - AIHM", html)

    await log_action(
        db,
        tenant_id=tenant.id,
        user_id=user.id,
        action="register",
        entity_type="user",
        entity_id=str(user.id),
    )

    token_data = {"sub": str(user.id), "tenant_id": str(tenant.id), "role": user.role}
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    await log_action(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="login",
        entity_type="user",
        entity_id=str(user.id),
    )

    token_data = {"sub": str(user.id), "tenant_id": str(user.tenant_id), "role": user.role}
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(data.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Refresh token invalide")

    token_data = {
        "sub": payload["sub"],
        "tenant_id": payload["tenant_id"],
        "role": payload["role"],
    }
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        tenant_id=str(current_user.tenant_id),
        email_verified=current_user.email_verified,
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def invite_user(
    data: InviteUserRequest,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if data.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Role invalide. Roles possibles: {', '.join(VALID_ROLES)}",
        )

    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email deja utilise")

    user = User(
        tenant_id=current_user.tenant_id,
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
    )
    db.add(user)
    await db.flush()

    await log_action(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="invite_user",
        entity_type="user",
        entity_id=str(user.id),
        details={"email": data.email, "role": data.role},
    )

    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        tenant_id=str(user.tenant_id),
        email_verified=user.email_verified,
    )


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.tenant_id == current_user.tenant_id))
    return [
        UserResponse(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            tenant_id=str(u.tenant_id),
            email_verified=u.email_verified,
        )
        for u in result.scalars().all()
    ]


@router.put("/me", response_model=UserResponse)
async def update_profile(
    data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if data.full_name is not None:
        current_user.full_name = data.full_name
    if data.email is not None and data.email != current_user.email:
        existing = await db.execute(select(User).where(User.email == data.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email deja utilise")
        current_user.email = data.email

    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        tenant_id=str(current_user.tenant_id),
        email_verified=current_user.email_verified,
    )


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    if len(data.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Le nouveau mot de passe doit faire au moins 8 caracteres",
        )
    current_user.password_hash = hash_password(data.new_password)

    await log_action(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="change_password",
        entity_type="user",
        entity_id=str(current_user.id),
    )

    return {"status": "ok"}


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    # Don't reveal if user exists or not for security
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if user:
        settings = get_settings()
        token = secrets.token_urlsafe(32)
        reset_token = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(reset_token)
        await db.flush()

        # Send password reset email
        reset_url = f"{settings.FRONTEND_URL}/reset-password/{token}"
        result_tenant = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant = result_tenant.scalar_one()
        html = render_email(
            "email/password_reset.html",
            user_name=user.full_name,
            reset_url=reset_url,
            tenant_name=tenant.name,
        )
        send_email.delay(user.email, "Reinitialisation de votre mot de passe - AIHM", html)

    # Always return success to avoid email enumeration
    return {
        "status": "ok",
        "message": "Si cet email existe, un lien de reinitialisation a ete envoye",
    }


@router.post("/reset-password/{token}")
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    token: str,
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PasswordResetToken).where(PasswordResetToken.token == token))
    reset_token = result.scalar_one_or_none()

    if not reset_token:
        raise HTTPException(status_code=400, detail="Token invalide ou expire")

    now = datetime.now(timezone.utc)
    if reset_token.expires_at < now:
        raise HTTPException(status_code=400, detail="Token invalide ou expire")

    if reset_token.used_at is not None:
        raise HTTPException(status_code=400, detail="Token invalide ou expire")

    # Update user password
    user_result = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = user_result.scalar_one()
    user.password_hash = hash_password(data.new_password)

    # Mark token as used
    reset_token.used_at = now
    await db.flush()

    await log_action(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="password_reset",
        entity_type="user",
        entity_id=str(user.id),
    )

    return {"status": "ok"}


@router.get("/verify-email/{token}")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmailVerificationToken).where(EmailVerificationToken.token == token)
    )
    verification_token = result.scalar_one_or_none()

    if not verification_token:
        raise HTTPException(status_code=400, detail="Token invalide ou expire")

    now = datetime.now(timezone.utc)
    if verification_token.expires_at < now:
        raise HTTPException(status_code=400, detail="Token invalide ou expire")

    if verification_token.used_at is not None:
        raise HTTPException(status_code=400, detail="Token invalide ou expire")

    # Verify user email
    user_result = await db.execute(select(User).where(User.id == verification_token.user_id))
    user = user_result.scalar_one()
    user.email_verified = True

    # Mark token as used
    verification_token.used_at = now
    await db.flush()

    await log_action(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="email_verified",
        entity_type="user",
        entity_id=str(user.id),
    )

    return {"status": "ok", "message": "Email verifie avec succes"}


@router.post("/resend-verification")
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.email_verified:
        raise HTTPException(status_code=400, detail="Email deja verifie")

    # Invalidate old tokens
    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == current_user.id,
            EmailVerificationToken.used_at.is_(None),
        )
    )
    old_tokens = result.scalars().all()
    now = datetime.now(timezone.utc)
    for old_token in old_tokens:
        old_token.used_at = now

    # Create new token
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    verification_token = EmailVerificationToken(
        user_id=current_user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(verification_token)
    await db.flush()

    # Send verification email
    verify_url = f"{settings.FRONTEND_URL}/verify-email/{token}"
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = tenant_result.scalar_one()
    html = render_email(
        "email/email_verification.html",
        user_name=current_user.full_name,
        verify_url=verify_url,
        tenant_name=tenant.name,
    )
    send_email.delay(current_user.email, "Verifiez votre adresse email - AIHM", html)

    return {"status": "ok"}


@router.get("/audit-logs")
async def get_audit_logs(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.tenant_id == current_user.tenant_id)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(min(limit, 100))
    )
    logs = result.scalars().all()
    return [
        {
            "id": str(log.id),
            "user_id": str(log.user_id) if log.user_id else None,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "details": log.details,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]
