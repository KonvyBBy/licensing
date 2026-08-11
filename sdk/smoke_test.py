"""End-to-end smoke test for the SDK against a running backend.

Usage:
  1. Start the backend:  uvicorn app.main:app --port 8765
  2. Run:  python sdk/smoke_test.py
"""
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(__file__))
from licensify import LicenseClient, LicenseError, SessionExpired

BASE = os.environ.get("LS_BASE", "http://127.0.0.1:8765")
ADMIN_EMAIL = os.environ.get("LS_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("LS_ADMIN_PASSWORD", "ChangeMe-1234567890!")

KEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def fake_key() -> str:
    import secrets
    return "-".join("".join(secrets.choice(KEY_ALPHABET) for _ in range(5)) for _ in range(5))


def main():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        r = c.post("/api/v1/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        r.raise_for_status()
        h = {"Authorization": "Bearer " + r.json()["access_token"]}

        r = c.post("/api/v1/admin/apps", json={"name": "SDK Smoke"}, headers=h)
        r.raise_for_status()
        app = r.json()

        r = c.post(f"/api/v1/admin/licenses/for/{app['id']}", json={"days": 30, "count": 1, "max_activations": 1}, headers=h)
        r.raise_for_status()
        key = r.json()[0]["key"]

    client = LicenseClient(BASE, app["client_id"], app["client_secret"])
    hwid = "sdk-smoke-machine-0001"

    # activate
    sess = client.activate(key=key, hwid=hwid)
    assert sess.valid
    print("[ok] activate ->", sess.session_token[:12] + "...")
    t1 = sess.session_token

    # verify rotates
    sess = client.verify(t1)
    assert sess.session_token != t1
    print("[ok] verify rotates token")
    t2 = sess.session_token

    # old token is dead
    try:
        client.verify(t1)
        raise SystemExit("[FAIL] old token still valid")
    except SessionExpired:
        print("[ok] old token rejected")

    # bad key rejected on activate
    try:
        client.activate(key=fake_key(), hwid="sdk-smoke-machine-0002")
        raise SystemExit("[FAIL] unknown key accepted")
    except LicenseError as e:
        assert e.status in (403, 404), e.status
        print(f"[ok] unknown key rejected ({e.status}: {e.detail})")

    # deactivate
    client.deactivate(t2)
    print("[ok] deactivate")

    # deactivating twice (stale token) must fail
    try:
        client.deactivate(t2)
        raise SystemExit("[FAIL] stale deactivate accepted")
    except LicenseError:
        print("[ok] stale deactivate rejected")

    print("\nAll SDK smoke checks passed.")


if __name__ == "__main__":
    main()
