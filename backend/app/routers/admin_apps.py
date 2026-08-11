from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import current_admin
from ..models import AdminUser, Application, License
from ..rate_limit import rate_limit
from ..schemas import AppCreate, AppOut, AppOutWithSecret, AppPatch
from ..security import audit, hash_token, new_client_id, new_client_secret

router = APIRouter(prefix="/admin/apps", tags=["admin-apps"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.post("", response_model=AppOutWithSecret, status_code=201)
async def create_app(
    payload: AppCreate,
    request: Request,
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    if not rate_limit(f"admin-{admin.id}", "admin:general"):
        raise HTTPException(429, "Too many requests")
    app = Application(
        name=payload.name,
        client_id=new_client_id(),
        client_secret_hash=hash_token(new_client_secret()),
        owner_id=admin.id,
    )
    secret = new_client_secret()
    app.client_secret_hash = hash_token(secret)
    db.add(app)
    await audit(
        db,
        actor_type="admin",
        actor_id=admin.id,
        action="app.create",
        target=app.name,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    await db.commit()
    await db.refresh(app)
    return AppOutWithSecret(
        id=app.id, name=app.name, client_id=app.client_id,
        status=app.status, created_at=app.created_at, client_secret=secret,
    )


@router.get("", response_model=list[AppOut])
async def list_apps(
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.scalars(select(Application).order_by(Application.created_at.desc()))
    return [
        AppOut(id=a.id, name=a.name, client_id=a.client_id, status=a.status, created_at=a.created_at)
        for a in rows
    ]


async def _get_app(db: AsyncSession, app_id: str) -> Application:
    app = await db.get(Application, app_id)
    if not app:
        raise HTTPException(404, "Application not found")
    return app


@router.patch("/{app_id}", response_model=AppOut)
async def patch_app(
    app_id: str,
    payload: AppPatch,
    request: Request,
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await _get_app(db, app_id)
    if payload.name is not None:
        app.name = payload.name
    if payload.status is not None:
        app.status = payload.status
    await audit(
        db, actor_type="admin", actor_id=admin.id, action="app.update",
        target=app.name, ip=_client_ip(request),
        details={"status": app.status},
    )
    await db.commit()
    await db.refresh(app)
    return AppOut(id=app.id, name=app.name, client_id=app.client_id, status=app.status, created_at=app.created_at)


@router.post("/{app_id}/regenerate-secret", response_model=AppOutWithSecret)
async def regenerate_secret(
    app_id: str,
    request: Request,
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await _get_app(db, app_id)
    secret = new_client_secret()
    app.client_secret_hash = hash_token(secret)
    await audit(
        db, actor_type="admin", actor_id=admin.id, action="app.regenerate_secret",
        target=app.name, ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(app)
    return AppOutWithSecret(
        id=app.id, name=app.name, client_id=app.client_id,
        status=app.status, created_at=app.created_at, client_secret=secret,
    )


@router.delete("/{app_id}", status_code=204)
async def delete_app(
    app_id: str,
    request: Request,
    admin: AdminUser = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await _get_app(db, app_id)
    license_count = await db.scalar(
        select(func.count()).select_from(License).where(License.app_id == app.id)
    )
    if license_count and license_count > 0:
        raise HTTPException(400, "Disable the app instead — it still has licenses.")
    await db.delete(app)
    await audit(
        db, actor_type="admin", actor_id=admin.id, action="app.delete",
        target=app.name, ip=_client_ip(request),
    )
    await db.commit()
