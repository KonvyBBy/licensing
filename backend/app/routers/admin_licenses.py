from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import current_admin
from ..models import AdminUser, Application, DeviceSession, License
from ..rate_limit import rate_limit
from ..schemas import LicenseBan, LicenseBulkCreate, LicenseCreate, LicenseOut, LicenseRevoke
from ..security import audit, generate_license_key, validate_key_format

router = APIRouter(prefix="/admin/licenses", tags=["admin-licenses"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _license_out(lic: License) -> LicenseOut:
    return LicenseOut(
        id=lic.id,
        key=lic.key,
        app_id=lic.app_id,
        status=lic.status,
        expires_at=lic.expires_at,
        hwid_bound=bool(lic.hwid_hash),
        max_activations=lic.max_activations,
        banned_reason=lic.banned_reason,
        created_at=lic.created_at,
    )


async def _app_for_admin(db: AsyncSession, admin: AdminUser, app_id: str) -> Application:
    app = await db.get(Application, app_id)
    if not app or app.owner_id != admin.id:
        raise HTTPException(404, "Application not found")
    return app


@router.post("/for/{app_id}", response_model=list[LicenseOut], status_code=201)
async def generate_for_app(
    app_id: str,
    payload: LicenseBulkCreate,
    request: Request,
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    if not rate_limit(f"admin-{admin.id}", "admin:general"):
        raise HTTPException(429, "Too many requests")
    await _app_for_admin(db, admin, app_id)

    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=payload.days) if payload.days and payload.days > 0 else None

    created = []
    seen = set()
    while len(created) < payload.count:
        key = generate_license_key()
        if key in seen:
            continue
        seen.add(key)
        exists = await db.scalar(select(License).where(License.key == key))
        if exists:
            continue
        lic = License(
            key=key,
            app_id=app_id,
            status="active",
            expires_at=expiry,
            max_activations=payload.max_activations,
            created_by=admin.id,
        )
        db.add(lic)
        created.append(lic)

    await audit(
        db, actor_type="admin", actor_id=admin.id, action="license.generate",
        target=app_id, ip=_client_ip(request),
        details={"count": len(created), "days": payload.days, "max_activations": payload.max_activations},
    )
    await db.commit()
    for lic in created:
        await db.refresh(lic)
    return [_license_out(lic) for lic in created]


@router.get("", response_model=list[LicenseOut])
async def list_licenses(
    app_id: str = Query(...),
    status_filter: str = Query(default="", alias="status"),
    search: str = Query(default=""),
    limit: int = Query(default=100, le=500),
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    await _app_for_admin(db, admin, app_id)
    q = select(License).where(License.app_id == app_id).order_by(License.created_at.desc())
    if status_filter:
        q = q.where(License.status == status_filter)
    if search:
        q = q.where(or_(License.key.ilike(f"%{search}%"), License.hwid_hash.ilike(f"%{search}%")))
    rows = await db.scalars(q.limit(limit))
    return [_license_out(lic) for lic in rows]


@router.get("/key/{key}", response_model=LicenseOut)
async def get_license(
    key: str,
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    lic = await db.scalar(select(License).where(License.key == key.upper()))
    if not lic:
        raise HTTPException(404, "License not found")
    app = await db.get(Application, lic.app_id)
    if not app or app.owner_id != admin.id:
        raise HTTPException(404, "License not found")
    return _license_out(lic)


async def _license_for_admin(db: AsyncSession, admin: AdminUser, key: str) -> License:
    lic = await db.scalar(select(License).where(License.key == key.upper()))
    if not lic:
        raise HTTPException(404, "License not found")
    app = await db.get(Application, lic.app_id)
    if not app or app.owner_id != admin.id:
        raise HTTPException(404, "License not found")
    return lic


@router.post("/revoke", response_model=LicenseOut)
async def revoke(
    payload: LicenseRevoke,
    request: Request,
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    lic = await _license_for_admin(db, admin, payload.key)
    lic.status = "revoked"
    # Kill all live sessions.
    await db.execute(
        DeviceSession.__table__.update().where(DeviceSession.license_id == lic.id).values(revoked=True)
    )
    await audit(
        db, actor_type="admin", actor_id=admin.id, action="license.revoke",
        target=lic.key, ip=_client_ip(request), details={"reason": payload.reason},
    )
    await db.commit()
    await db.refresh(lic)
    return _license_out(lic)


@router.post("/ban", response_model=LicenseOut)
async def ban(
    payload: LicenseBan,
    request: Request,
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    lic = await _license_for_admin(db, admin, payload.key)
    lic.status = "banned"
    lic.banned_reason = payload.reason
    await db.execute(
        DeviceSession.__table__.update().where(DeviceSession.license_id == lic.id).values(revoked=True)
    )
    await audit(
        db, actor_type="admin", actor_id=admin.id, action="license.ban",
        target=lic.key, ip=_client_ip(request), details={"reason": payload.reason},
    )
    await db.commit()
    await db.refresh(lic)
    return _license_out(lic)


@router.post("/reset", response_model=LicenseOut)
async def reset(
    payload: LicenseRevoke,
    request: Request,
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Unbind the HWID and revoke all sessions so the key can be used again."""
    lic = await _license_for_admin(db, admin, payload.key)
    lic.hwid_hash = None
    await db.execute(
        DeviceSession.__table__.update().where(DeviceSession.license_id == lic.id).values(revoked=True)
    )
    await audit(
        db, actor_type="admin", actor_id=admin.id, action="license.reset",
        target=lic.key, ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(lic)
    return _license_out(lic)
