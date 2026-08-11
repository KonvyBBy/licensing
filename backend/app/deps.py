from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models import AdminUser
from .security import decode_admin_access_token


async def current_admin(
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = authorization[7:].strip()
    try:
        admin_id = decode_admin_access_token(token)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    admin = await db.scalar(select(AdminUser).where(AdminUser.id == admin_id))
    if not admin or not admin.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return admin


async def bootstrap_admin(db: AsyncSession) -> None:
    """Create the initial admin account if none exists."""
    from .config import settings
    from .security import hash_password

    exists = await db.scalar(select(AdminUser.id).limit(1))
    if exists:
        return
    if settings.ENVIRONMENT == "production" and settings.ADMIN_PASSWORD == "ChangeMe-1234567890!":
        raise RuntimeError(
            "Set ADMIN_PASSWORD to a strong value in production before first run."
        )
    admin = AdminUser(
        email=settings.ADMIN_EMAIL.lower(),
        password_hash=hash_password(settings.ADMIN_PASSWORD),
        roles=["admin"],
    )
    db.add(admin)
    await db.commit()
