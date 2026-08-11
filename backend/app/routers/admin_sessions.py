from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import current_admin
from ..models import AdminUser, Application, DeviceSession, License
from ..schemas import LicenseRevoke
from ..security import audit

router = APIRouter(prefix="/admin/sessions", tags=["admin-sessions"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.get("")
async def list_sessions(
    license_key: str = Query(...),
    limit: int = Query(default=100, le=500),
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    lic = await db.scalar(select(License).where(License.key == license_key.upper()))
    if not lic:
        raise HTTPException(404, "License not found")
    app = await db.get(Application, lic.app_id)
    if not app or app.owner_id != admin.id:
        raise HTTPException(404, "License not found")
    rows = await db.scalars(
        select(DeviceSession)
        .where(DeviceSession.license_id == lic.id)
        .order_by(DeviceSession.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": s.id,
            "created_at": s.created_at,
            "expires_at": s.expires_at,
            "last_seen_at": s.last_seen_at,
            "ip": s.ip,
            "user_agent": s.user_agent,
            "revoked": s.revoked,
        }
        for s in rows
    ]


@router.post("/{session_id}/revoke", status_code=204)
async def revoke_session(
    session_id: str,
    request: Request,
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    sess = await db.get(DeviceSession, session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    lic = await db.get(License, sess.license_id)
    app = await db.get(Application, lic.app_id)
    if not app or app.owner_id != admin.id:
        raise HTTPException(404, "Session not found")
    sess.revoked = True
    await audit(
        db, actor_type="admin", actor_id=admin.id, action="session.revoke",
        target=lic.key, ip=_client_ip(request),
    )
    await db.commit()
