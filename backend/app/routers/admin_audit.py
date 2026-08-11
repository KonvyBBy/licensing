from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import current_admin
from ..models import AdminUser, Application, AuditLog, DeviceSession, License
from ..schemas import AuditOut, StatsOut

router = APIRouter(prefix="/admin", tags=["admin-audit"])


@router.get("/audit", response_model=list[AuditOut])
async def list_audit(
    limit: int = Query(default=100, le=500),
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    return [
        AuditOut(
            id=e.id, actor_type=e.actor_type, actor_id=e.actor_id, action=e.action,
            target=e.target, ip=e.ip, created_at=e.created_at, details=e.details,
        )
        for e in rows
    ]


@router.get("/stats", response_model=StatsOut)
async def stats(
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    apps = await db.scalar(select(func.count()).select_from(Application))
    licenses = await db.scalar(select(func.count()).select_from(License))
    active_licenses = await db.scalar(
        select(func.count()).select_from(License).where(License.status == "active")
    )
    active_sessions = await db.scalar(
        select(func.count()).select_from(DeviceSession).where(DeviceSession.revoked.is_(False))
    )
    return StatsOut(
        apps=apps or 0,
        licenses=licenses or 0,
        active_sessions=active_sessions or 0,
        active_licenses=active_licenses or 0,
    )
