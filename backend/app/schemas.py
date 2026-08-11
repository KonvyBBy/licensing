from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


def normalize_email(email: str) -> str:
    return email.strip().lower()


# ---------------------------------------------------------------- admin
class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class AdminRefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AdminMe(BaseModel):
    id: str
    email: str
    roles: List[str]

    @classmethod
    def from_model(cls, admin) -> "AdminMe":
        return cls(id=admin.id, email=admin.email, roles=admin.roles or [])


class AdminPasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)

    @field_validator("new_password")
    @classmethod
    def _strong(cls, v: str) -> str:
        if len(v) < 10:
            raise ValueError("Password must be at least 10 characters")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain a number")
        return v


# ---------------------------------------------------------------- applications
class AppCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class AppOut(BaseModel):
    id: str
    name: str
    client_id: str
    status: str
    created_at: datetime


class AppOutWithSecret(AppOut):
    client_secret: str


class AppPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is not None and v not in {"active", "disabled"}:
            raise ValueError("status must be active or disabled")
        return v


class AppRegenerateSecret(BaseModel):
    new_client_secret: str


# ---------------------------------------------------------------- licenses
class LicenseCreate(BaseModel):
    # Legacy field: validity in days (0 = lifetime). Still supported for
    # backward compatibility; prefer `duration` + `unit` for finer control.
    days: int = Field(default=0, ge=0, le=100000)
    # Validity as a quantity + unit. When `unit` is set it takes precedence
    # over `days`. `lifetime` means no expiry.
    duration: int = Field(default=0, ge=0, le=100000)
    unit: str = Field(default="")
    max_activations: int = Field(default=1, ge=1, le=100)

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        v = v.lower().strip()
        allowed = {"", "minutes", "hours", "days", "weeks", "months", "years", "lifetime"}
        if v not in allowed:
            raise ValueError("unit must be minutes|hours|days|weeks|months|years|lifetime")
        return v


class LicenseBulkCreate(LicenseCreate):
    count: int = Field(default=1, ge=1, le=100)


class LicenseOut(BaseModel):
    id: str
    key: str
    app_id: str
    status: str
    expires_at: Optional[datetime]
    hwid_bound: bool
    max_activations: int
    banned_reason: str
    created_at: datetime


class LicenseRevoke(BaseModel):
    key: str
    reason: str = ""


class LicenseBan(BaseModel):
    key: str
    reason: str = Field(min_length=1)


# ---------------------------------------------------------------- client (SDK)
class ActivateRequest(BaseModel):
    app_id: str
    app_secret: str
    key: str
    hwid: str = Field(min_length=8, max_length=256)


class VerifyRequest(BaseModel):
    app_id: str
    session_token: str


class DeactivateRequest(BaseModel):
    app_id: str
    session_token: str


class AuthSuccess(BaseModel):
    ok: bool = True
    session_token: str
    expires_in: int
    expires_at: Optional[datetime]
    valid: bool = True


class VerifySuccess(BaseModel):
    ok: bool = True
    valid: bool = True
    session_token: str
    expires_in: int
    expires_at: Optional[datetime]
    app_id: str
    license_key: str


# ---------------------------------------------------------------- audit / stats
class AuditOut(BaseModel):
    id: str
    actor_type: str
    actor_id: str
    action: str
    target: str
    ip: str
    created_at: datetime
    details: Optional[dict]


class StatsOut(BaseModel):
    apps: int
    licenses: int
    active_sessions: int
    active_licenses: int
