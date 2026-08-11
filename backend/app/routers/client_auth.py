from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import ensure_aware, get_db
from ..duration import expiry_from_duration
from ..models import Application, DeviceSession, License
from ..rate_limit import rate_limit
from ..schemas import (
    ActivateRequest,
    AuthSuccess,
    DeactivateRequest,
    VerifyRequest,
    VerifySuccess,
)
from ..security import (
    audit,
    get_active_application,
    hash_hwid,
    hash_token,
    new_token,
    validate_key_format,
    verify_hwid,
)

router = APIRouter(prefix="/auth", tags=["client-auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _session_expiry(license_expiry: datetime | None, now: datetime) -> datetime:
    """Session expires in SESSION_HOURS, but never outlives the license."""
    license_expiry = ensure_aware(license_expiry)
    candidate = now + timedelta(hours=settings.SESSION_HOURS)
    if license_expiry and license_expiry < candidate:
        return license_expiry
    return candidate


async def _active_session_count(db: AsyncSession, license_id: str) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(DeviceSession)
        .where(DeviceSession.license_id == license_id, DeviceSession.revoked.is_(False))
    )


@router.post("/activate", response_model=AuthSuccess)
async def activate(
    payload: ActivateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ip = _client_ip(request)
    if not rate_limit(f"activate:{ip}", "client:activate"):
        raise HTTPException(429, "Too many activation attempts. Try again shortly.")

    app = await get_active_application(db, payload.app_id, payload.app_secret)
    if not app:
        await audit(
            db, actor_type="app", actor_id=payload.app_id, action="auth.activate.rejected",
            target="bad-app-credentials", ip=ip,
        )
        await db.commit()
        raise HTTPException(401, "Invalid application credentials")

    key = payload.key.upper()
    if not validate_key_format(key):
        raise HTTPException(400, "Malformed license key")

    lic = await db.scalar(select(License).where(License.key == key, License.app_id == app.id))
    now = datetime.now(timezone.utc)

    if not lic:
        await audit(
            db, actor_type="app", actor_id=payload.app_id, action="auth.activate.rejected",
            target=key, ip=ip, details={"reason": "unknown key"},
        )
        await db.commit()
        raise HTTPException(404, "Invalid license key")

    if lic.status == "banned":
        await audit(
            db, actor_type="app", actor_id=payload.app_id, action="auth.activate.rejected",
            target=key, ip=ip, details={"reason": "banned"},
        )
        await db.commit()
        raise HTTPException(403, "This license key has been banned")

    if lic.status != "active":
        await audit(
            db, actor_type="app", actor_id=payload.app_id, action="auth.activate.rejected",
            target=key, ip=ip, details={"reason": lic.status},
        )
        await db.commit()
        raise HTTPException(403, f"License key is {lic.status}")

    if ensure_aware(lic.expires_at) and ensure_aware(lic.expires_at) < now:
        lic.status = "expired"
        await db.commit()
        raise HTTPException(403, "License key has expired")

    new_hwid_hash = hash_hwid(payload.hwid)

    # HWID binding: if already bound to a different device, reject.
    if lic.hwid_hash and not verify_hwid(payload.hwid, lic.hwid_hash):
        await audit(
            db, actor_type="app", actor_id=payload.app_id, action="auth.activate.rejected",
            target=key, ip=ip, details={"reason": "hwid-mismatch"},
        )
        await db.commit()
        raise HTTPException(403, "License key is already bound to another device")

    # Check activation limit (same device is allowed to refresh).
    active = await _active_session_count(db, lic.id)
    if lic.hwid_hash and verify_hwid(payload.hwid, lic.hwid_hash):
        pass  # same device — allowed regardless of count
    elif active >= lic.max_activations:
        await audit(
            db, actor_type="app", actor_id=payload.app_id, action="auth.activate.rejected",
            target=key, ip=ip, details={"reason": "max-activations"},
        )
        await db.commit()
        raise HTTPException(403, "Maximum activations reached for this key")

    # Bind HWID on first activation.
    lic.hwid_hash = new_hwid_hash

    # Countdown starts on first use: stamp the expiry only now, so the license
    # does not rot while sitting unused on a seller's shelf.
    if lic.expires_at is None and lic.validity_value and lic.validity_value > 0:
        lic.expires_at = expiry_from_duration(lic.validity_value, lic.validity_unit, now)

    token = new_token(32)
    expiry = _session_expiry(lic.expires_at, now)
    db.add(
        DeviceSession(
            license_id=lic.id,
            token_hash=hash_token(token),
            expires_at=expiry,
            ip=ip,
            user_agent=request.headers.get("user-agent", ""),
        )
    )
    await audit(
        db, actor_type="app", actor_id=payload.app_id, action="auth.activate",
        target=key, ip=ip, details={"expires_at": lic.expires_at.isoformat() if lic.expires_at else None},
    )
    await db.commit()
    return AuthSuccess(
        session_token=token,
        expires_in=int((expiry - now).total_seconds()),
        expires_at=expiry,
    )


@router.post("/verify", response_model=VerifySuccess)
async def verify(
    payload: VerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ip = _client_ip(request)
    if not rate_limit(f"verify:{ip}", "client:verify"):
        raise HTTPException(429, "Too many requests")

    app = await db.scalar(select(Application).where(Application.client_id == payload.app_id))
    if not app or app.status != "active":
        raise HTTPException(401, "Application is not active")

    sess = await db.scalar(
        select(DeviceSession).where(DeviceSession.token_hash == hash_token(payload.session_token))
    )
    now = datetime.now(timezone.utc)
    if not sess or sess.revoked or ensure_aware(sess.expires_at) < now:
        raise HTTPException(401, "Session expired or revoked")

    lic = await db.get(License, sess.license_id)
    if not lic:
        raise HTTPException(401, "Session invalid")

    if lic.status == "banned":
        sess.revoked = True
        await db.commit()
        raise HTTPException(403, "License key has been banned")

    if lic.status != "active":
        sess.revoked = True
        await db.commit()
        raise HTTPException(403, f"License key is {lic.status}")

    if ensure_aware(lic.expires_at) and ensure_aware(lic.expires_at) < now:
        lic.status = "expired"
        sess.revoked = True
        await db.commit()
        raise HTTPException(403, "License key has expired")

    # Rotation: old session dies, new short-lived token issued.
    new_expiry = _session_expiry(lic.expires_at, now)
    sess.revoked = True
    new_token_value = new_token(32)
    db.add(
        DeviceSession(
            license_id=lic.id,
            token_hash=hash_token(new_token_value),
            expires_at=new_expiry,
            ip=ip,
            user_agent=request.headers.get("user-agent", ""),
        )
    )
    await audit(
        db, actor_type="app", actor_id=payload.app_id, action="auth.verify",
        target=lic.key, ip=ip,
    )
    await db.commit()
    return VerifySuccess(
        session_token=new_token_value,
        expires_in=int((new_expiry - now).total_seconds()),
        expires_at=new_expiry,
        app_id=app.client_id,
        license_key=lic.key,
    )


@router.post("/deactivate", status_code=204)
async def deactivate(
    payload: DeactivateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ip = _client_ip(request)
    app = await db.scalar(select(Application).where(Application.client_id == payload.app_id))
    if not app or app.status != "active":
        raise HTTPException(401, "Application is not active")

    sess = await db.scalar(
        select(DeviceSession).where(DeviceSession.token_hash == hash_token(payload.session_token))
    )
    if not sess or sess.revoked:
        raise HTTPException(404, "Session not found or already revoked")
    lic = await db.get(License, sess.license_id)
    sess.revoked = True

    # Unbind HWID only when this was the last live session for the license.
    # A rotated/replayed token is rejected above, so this cannot be abused to
    # unbind a license while another device still holds a live session.
    if lic:
        remaining = await _active_session_count(db, lic.id)
        if remaining <= 0:
            lic.hwid_hash = None
        await audit(
            db, actor_type="app", actor_id=payload.app_id, action="auth.deactivate",
            target=lic.key, ip=ip,
        )
    await db.commit()
