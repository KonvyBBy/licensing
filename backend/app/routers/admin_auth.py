from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import ensure_aware, get_db
from ..deps import current_admin
from ..models import AdminRefreshToken, AdminUser
from ..rate_limit import rate_limit
from ..schemas import (
    AdminMe,
    AdminPasswordChange,
    AdminRefreshRequest,
    AdminLoginRequest,
    TokenPair,
)
from ..security import (
    create_admin_access_token,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)

router = APIRouter(prefix="/admin", tags=["admin-auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _issue_tokens(db: AsyncSession, admin: AdminUser, request: Request) -> TokenPair:
    access = create_admin_access_token(admin.id)
    refresh = new_token(32)
    db.add(
        AdminRefreshToken(
            admin_id=admin.id,
            token_hash=hash_token(refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.ADMIN_REFRESH_DAYS),
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
    )
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ADMIN_ACCESS_MINUTES * 60,
    )


@router.post("/login", response_model=TokenPair)
async def login(payload: AdminLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip = _client_ip(request)
    if not rate_limit(f"admin-login:{ip}", "admin:login"):
        raise HTTPException(429, "Too many attempts. Try again shortly.")

    admin = await db.scalar(select(AdminUser).where(AdminUser.email == payload.email.lower()))
    if not admin:
        # Dummy verify to keep timing uniform.
        verify_password(payload.password, hash_password("dummy-password-for-timing!"))
        raise HTTPException(401, "Invalid email or password")

    now = datetime.now(timezone.utc)
    if ensure_aware(admin.locked_until) and ensure_aware(admin.locked_until) > now:
        raise HTTPException(423, "Account temporarily locked. Try again later.")

    if not verify_password(payload.password, admin.password_hash):
        admin.failed_login_attempts += 1
        if admin.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            admin.locked_until = now + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
            admin.failed_login_attempts = 0
        await db.commit()
        raise HTTPException(401, "Invalid email or password")

    admin.failed_login_attempts = 0
    admin.locked_until = None
    pair = _issue_tokens(db, admin, request)
    await db.commit()
    return pair


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: AdminRefreshRequest, request: Request, db: AsyncSession = Depends(get_db)):
    token_hash = hash_token(payload.refresh_token)
    stored = await db.scalar(
        select(AdminRefreshToken).where(AdminRefreshToken.token_hash == token_hash)
    )
    now = datetime.now(timezone.utc)
    if not stored or stored.revoked or ensure_aware(stored.expires_at) < now:
        raise HTTPException(401, "Invalid refresh token")

    # Rotation: revoke the old token, issue a new pair.
    stored.revoked = True
    admin = await db.get(AdminUser, stored.admin_id)
    if not admin or not admin.is_active:
        raise HTTPException(401, "Account unavailable")
    access = create_admin_access_token(admin.id)
    new_refresh = new_token(32)
    stored.replaced_by = hash_token(new_refresh)
    db.add(
        AdminRefreshToken(
            admin_id=admin.id,
            token_hash=hash_token(new_refresh),
            expires_at=now + timedelta(days=settings.ADMIN_REFRESH_DAYS),
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
    )
    await db.commit()
    return TokenPair(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=settings.ADMIN_ACCESS_MINUTES * 60,
    )


@router.post("/logout", status_code=204)
async def logout(payload: AdminRefreshRequest, db: AsyncSession = Depends(get_db)):
    stored = await db.scalar(
        select(AdminRefreshToken).where(AdminRefreshToken.token_hash == hash_token(payload.refresh_token))
    )
    if stored:
        stored.revoked = True
        await db.commit()


@router.get("/me", response_model=AdminMe)
async def me(admin: AdminUser = Depends(current_admin)):
    return AdminMe.from_model(admin)


@router.post("/change-password", status_code=204)
async def change_password(
    payload: AdminPasswordChange,
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(payload.current_password, admin.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    admin.password_hash = hash_password(payload.new_password)
    # Revoke all admin sessions on password change.
    await db.execute(
        AdminRefreshToken.__table__.update()
        .where(AdminRefreshToken.admin_id == admin.id)
        .values(revoked=True)
    )
    await db.commit()
