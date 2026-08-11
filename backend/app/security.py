import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Application, AuditLog

# ---------------------------------------------------------------- password hashing
_argon2 = PasswordHasher()


def hash_password(password: str) -> str:
    return _argon2.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _argon2.verify(password_hash, password)
    except Exception:
        return False


# ---------------------------------------------------------------- hmac helpers
def hmac_sha256(secret: str, data: str) -> str:
    return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_hwid(raw_hwid: str) -> str:
    """HMAC the device id with the server secret so raw device info is never stored."""
    return hmac_sha256(settings.SECRET_KEY, "hwid:" + raw_hwid)


def verify_hwid(raw_hwid: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_hwid(raw_hwid), stored_hash)


# ---------------------------------------------------------------- random tokens
def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_client_secret() -> str:
    return "csec_" + secrets.token_urlsafe(24)


def new_client_id() -> str:
    return "app_" + secrets.token_urlsafe(12)


# ---------------------------------------------------------------- admin JWT (access)
def create_admin_access_token(admin_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": admin_id,
        "typ": "admin_access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ADMIN_ACCESS_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_admin_access_token(token: str) -> str:
    """Return the admin id or raise ValueError."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        raise ValueError("invalid token")
    if payload.get("typ") != "admin_access":
        raise ValueError("wrong token type")
    return payload["sub"]


# ---------------------------------------------------------------- key generation (server-only)
KEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L


def generate_license_key() -> str:
    """Format: XXXXX-XXXXX-XXXXX-XXXXX-XXXXX. Minting is server-only."""
    groups = []
    for _ in range(5):
        groups.append("".join(secrets.choice(KEY_ALPHABET) for _ in range(5)))
    return "-".join(groups)


def validate_key_format(key: str) -> bool:
    parts = key.upper().split("-")
    if len(parts) != 5 or any(len(p) != 5 for p in parts):
        return False
    return all(all(c in KEY_ALPHABET for c in p) for p in parts)


# ---------------------------------------------------------------- audit
async def audit(
    db: AsyncSession,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    target: str = "",
    ip: str = "",
    user_agent: str = "",
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target=target,
            ip=ip,
            user_agent=user_agent,
            details=details,
        )
    )


async def get_active_application(
    db: AsyncSession, client_id: str, client_secret: str
) -> Application | None:
    app = await db.scalar(select(Application).where(Application.client_id == client_id))
    if not app or app.status != "active":
        return None
    if not hmac.compare_digest(hash_token(client_secret), app.client_secret_hash):
        return None
    return app
