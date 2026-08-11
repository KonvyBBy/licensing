"""End-to-end integration tests for the license server (SQLite, in-memory).

Run from backend/:  ../.venv/Scripts/python.exe -m pytest tests -q
"""
import os
import sys

import pytest
import httpx

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_license.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-characters-long!")
os.environ.setdefault("ADMIN_EMAIL", "testadmin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "TestPass-123456!")
os.environ.setdefault("DISABLE_RATE_LIMIT", "1")

sys.path.insert(0, os.path.dirname(__file__))

from app.main import app  # noqa: E402
from app.database import engine  # noqa: E402
from app.security import validate_key_format  # noqa: E402

ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]


@pytest.fixture(scope="session", autouse=True)
async def _init():
    from app.database import Base, init_db
    from app.deps import bootstrap_admin
    from app.database import SessionLocal

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await init_db()
    async with SessionLocal() as db:
        await bootstrap_admin(db)
    yield


@pytest.fixture(scope="session")
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session")
async def admin_tokens(client):
    r = await client.post("/api/v1/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"access": data["access_token"], "refresh": data["refresh_token"]}


@pytest.fixture(scope="session")
def auth_headers(admin_tokens):
    return {"Authorization": f"Bearer {admin_tokens['access']}"}


@pytest.fixture(scope="session")
async def app_with_secret(client, auth_headers):
    r = await client.post("/api/v1/admin/apps", json={"name": "Test App"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(scope="session")
async def app_creds(app_with_secret):
    return {"app_id": app_with_secret["client_id"], "app_secret": app_with_secret["client_secret"]}


@pytest.fixture(scope="session")
async def license_key(client, auth_headers, app_with_secret):
    r = await client.post(
        f"/api/v1/admin/licenses/for/{app_with_secret['id']}",
        json={"days": 30, "count": 1, "max_activations": 1},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()[0]["key"]


# ------------------------------------------------------------------ admin auth
async def test_login_wrong_password(client):
    r = await client.post("/api/v1/admin/login", json={"email": ADMIN_EMAIL, "password": "wrong-password"})
    assert r.status_code == 401


async def test_refresh_rotation(client, admin_tokens):
    r = await client.post("/api/v1/admin/refresh", json={"refresh_token": admin_tokens["refresh"]})
    assert r.status_code == 200
    new_refresh = r.json()["refresh_token"]
    assert new_refresh != admin_tokens["refresh"]
    # Old refresh token must now be rejected.
    r2 = await client.post("/api/v1/admin/refresh", json={"refresh_token": admin_tokens["refresh"]})
    assert r2.status_code == 401


async def test_me(client, auth_headers):
    r = await client.get("/api/v1/admin/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["email"] == ADMIN_EMAIL


async def test_admin_requires_auth(client):
    assert (await client.get("/api/v1/admin/me")).status_code == 401
    assert (await client.get("/api/v1/admin/apps")).status_code == 401


# ------------------------------------------------------------------ apps
async def test_generate_secret_format(app_with_secret):
    assert app_with_secret["client_secret"].startswith("csec_")
    assert app_with_secret["status"] == "active"


async def test_disable_and_regenerate(client, auth_headers):
    r = await client.post("/api/v1/admin/apps", json={"name": "Regen App"}, headers=auth_headers)
    app = r.json()

    r = await client.patch(
        f"/api/v1/admin/apps/{app['id']}",
        json={"status": "disabled"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "disabled"

    r = await client.post(
        f"/api/v1/admin/apps/{app['id']}/regenerate-secret",
        json={},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["client_secret"] != app["client_secret"]

    # Re-enable.
    await client.patch(
        f"/api/v1/admin/apps/{app['id']}",
        json={"status": "active"},
        headers=auth_headers,
    )


# ------------------------------------------------------------------ licenses
async def test_generated_key_format(license_key):
    assert validate_key_format(license_key)
    assert license_key.count("-") == 4
    assert len(license_key) == 29


async def test_list_licenses(client, auth_headers, app_with_secret, license_key):
    r = await client.get(f"/api/v1/admin/licenses?app_id={app_with_secret['id']}", headers=auth_headers)
    assert r.status_code == 200
    keys = [l["key"] for l in r.json()]
    assert license_key in keys


async def test_generate_duration_units(client, auth_headers, app_with_secret):
    from datetime import datetime, timedelta, timezone

    cases = [
        {"duration": 90, "unit": "minutes"},
        {"duration": 6, "unit": "hours"},
        {"duration": 14, "unit": "weeks"},
        {"duration": 3, "unit": "months"},
        {"duration": 2, "unit": "years"},
        {"duration": 0, "unit": "lifetime"},
    ]
    for payload in cases:
        r = await client.post(
            f"/api/v1/admin/licenses/for/{app_with_secret['id']}",
            json={**payload, "count": 1, "max_activations": 1},
            headers=auth_headers,
        )
        assert r.status_code == 201, (payload, r.text)
        lic = r.json()[0]
        if payload["unit"] == "lifetime":
            assert lic["expires_at"] is None
        else:
            assert lic["expires_at"] is not None
            exp = datetime.fromisoformat(lic["expires_at"].replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            assert exp > datetime.now(timezone.utc)

    # legacy `days` still works
    r = await client.post(
        f"/api/v1/admin/licenses/for/{app_with_secret['id']}",
        json={"days": 30, "count": 1, "max_activations": 1},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    exp = datetime.fromisoformat(r.json()[0]["expires_at"].replace("Z", "+00:00"))
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    assert exp > datetime.now(timezone.utc)


async def test_generate_duration_requires_positive(client, auth_headers, app_with_secret):
    r = await client.post(
        f"/api/v1/admin/licenses/for/{app_with_secret['id']}",
        json={"duration": 0, "unit": "days", "count": 1, "max_activations": 1},
        headers=auth_headers,
    )
    assert r.status_code == 400


# ------------------------------------------------------------------ client auth flow
async def test_activate_verify_deactivate(client, app_creds, license_key):
    hwid = "machine-abc-12345"

    # activate
    r = await client.post(
        "/api/v1/auth/activate",
        json={"app_id": app_creds["app_id"], "app_secret": app_creds["app_secret"], "key": license_key, "hwid": hwid},
    )
    assert r.status_code == 200, r.text
    session_token = r.json()["session_token"]
    assert r.json()["valid"] is True

    # verify (rotates token)
    r = await client.post(
        "/api/v1/auth/verify",
        json={"app_id": app_creds["app_id"], "session_token": session_token},
    )
    assert r.status_code == 200, r.text
    new_token = r.json()["session_token"]
    assert new_token != session_token

    # old token must now be rejected
    r = await client.post(
        "/api/v1/auth/verify",
        json={"app_id": app_creds["app_id"], "session_token": session_token},
    )
    assert r.status_code == 401

    # new token works
    r = await client.post(
        "/api/v1/auth/verify",
        json={"app_id": app_creds["app_id"], "session_token": new_token},
    )
    assert r.status_code == 200
    new_token = r.json()["session_token"]

    # deactivate with the CURRENT (rotated) token
    r = await client.post(
        "/api/v1/auth/deactivate",
        json={"app_id": app_creds["app_id"], "session_token": new_token},
    )
    assert r.status_code == 204


async def test_hwid_mismatch_rejected(client, app_creds, license_key):
    # First activation binds hwid "device-A".
    r = await client.post(
        "/api/v1/auth/activate",
        json={"app_id": app_creds["app_id"], "app_secret": app_creds["app_secret"], "key": license_key, "hwid": "device-A-12345"},
    )
    assert r.status_code == 200, r.text

    # Second device must be rejected.
    r = await client.post(
        "/api/v1/auth/activate",
        json={"app_id": app_creds["app_id"], "app_secret": app_creds["app_secret"], "key": license_key, "hwid": "device-B-12345"},
    )
    assert r.status_code == 403


async def test_activate_rejects_bad_secret(client, app_creds, license_key):
    r = await client.post(
        "/api/v1/auth/activate",
        json={"app_id": app_creds["app_id"], "app_secret": "csec_wrongsecret", "key": license_key, "hwid": "machine-xyz-999"},
    )
    assert r.status_code == 401


async def test_activate_rejects_unknown_key(client, app_creds):
    r = await client.post(
        "/api/v1/auth/activate",
        json={
            "app_id": app_creds["app_id"],
            "app_secret": app_creds["app_secret"],
            "key": "ABCDE-FGHJK-MNPQR-STUVW-23456",
            "hwid": "machine-xyz-999",
        },
    )
    assert r.status_code == 404


# ------------------------------------------------------------------ admin enforcement
async def test_revoke_kills_sessions(client, auth_headers, app_creds, app_with_secret):
    # fresh key
    r = await client.post(
        f"/api/v1/admin/licenses/for/{app_with_secret['id']}",
        json={"days": 30, "count": 1, "max_activations": 1},
        headers=auth_headers,
    )
    key = r.json()[0]["key"]
    r = await client.post(
        "/api/v1/auth/activate",
        json={"app_id": app_creds["app_id"], "app_secret": app_creds["app_secret"], "key": key, "hwid": "machine-revoke-1"},
    )
    token = r.json()["session_token"]

    r = await client.post("/api/v1/admin/licenses/revoke", json={"key": key, "reason": "test"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "revoked"

    # session must now be dead
    r = await client.post("/api/v1/auth/verify", json={"app_id": app_creds["app_id"], "session_token": token})
    assert r.status_code == 401


async def test_reset_unbinds_hwid(client, auth_headers, app_creds, app_with_secret):
    r = await client.post(
        f"/api/v1/admin/licenses/for/{app_with_secret['id']}",
        json={"days": 30, "count": 1, "max_activations": 1},
        headers=auth_headers,
    )
    key = r.json()[0]["key"]

    await client.post(
        "/api/v1/auth/activate",
        json={"app_id": app_creds["app_id"], "app_secret": app_creds["app_secret"], "key": key, "hwid": "machine-reset-1"},
    )
    r = await client.post(
        "/api/v1/auth/activate",
        json={"app_id": app_creds["app_id"], "app_secret": app_creds["app_secret"], "key": key, "hwid": "machine-reset-2"},
    )
    assert r.status_code == 403  # bound to first device

    await client.post("/api/v1/admin/licenses/reset", json={"key": key, "reason": ""}, headers=auth_headers)

    r = await client.post(
        "/api/v1/auth/activate",
        json={"app_id": app_creds["app_id"], "app_secret": app_creds["app_secret"], "key": key, "hwid": "machine-reset-2"},
    )
    assert r.status_code == 200, r.text


async def test_ban(client, auth_headers, app_creds, app_with_secret):
    r = await client.post(
        f"/api/v1/admin/licenses/for/{app_with_secret['id']}",
        json={"days": 30, "count": 1, "max_activations": 1},
        headers=auth_headers,
    )
    key = r.json()[0]["key"]

    r = await client.post("/api/v1/admin/licenses/ban", json={"key": key, "reason": "chargeback"}, headers=auth_headers)
    assert r.status_code == 200

    r = await client.post(
        "/api/v1/auth/activate",
        json={"app_id": app_creds["app_id"], "app_secret": app_creds["app_secret"], "key": key, "hwid": "machine-ban-1"},
    )
    assert r.status_code == 403


# ------------------------------------------------------------------ sessions + audit
async def test_sessions_listed(client, auth_headers, app_creds, app_with_secret):
    r = await client.post(
        f"/api/v1/admin/licenses/for/{app_with_secret['id']}",
        json={"days": 30, "count": 1, "max_activations": 1},
        headers=auth_headers,
    )
    key = r.json()[0]["key"]
    await client.post(
        "/api/v1/auth/activate",
        json={"app_id": app_creds["app_id"], "app_secret": app_creds["app_secret"], "key": key, "hwid": "machine-sess-1"},
    )
    r = await client.get(f"/api/v1/admin/sessions?license_key={key}", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1
    assert r.json()[0]["revoked"] is False


async def test_audit_log(client, auth_headers):
    r = await client.get("/api/v1/admin/audit", headers=auth_headers)
    assert r.status_code == 200
    actions = {e["action"] for e in r.json()}
    assert "auth.activate" in actions
    assert "license.generate" in actions


async def test_stats(client, auth_headers):
    r = await client.get("/api/v1/admin/stats", headers=auth_headers)
    assert r.status_code == 200
    s = r.json()
    assert s["apps"] >= 1
    assert s["licenses"] >= 1


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ------------------------------------------------------------------ rate limiting
def test_rate_limit_blocks_excess():
    import app.rate_limit as rl

    rl.DISABLED = False
    rl._buckets.clear()
    window, max_req = rl.LIMITS["admin:login"]
    assert max_req == 5
    for _ in range(max_req):
        assert rl.rate_limit("unit-test-ip", "admin:login") is True
    assert rl.rate_limit("unit-test-ip", "admin:login") is False
    assert rl.rate_limit("other-ip", "admin:login") is True
    rl._buckets.clear()
    rl.DISABLED = True
