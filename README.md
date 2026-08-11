# LicenseServer

Production-grade self-hosted licensing platform: FastAPI + Postgres backend,
admin dashboard, and an official Python SDK.

The **server is the sole authority** for license validity. Clients only forward
activation/verification requests; nothing about key generation or validation
lives in the client, so decompiling your app cannot mint or extend licenses.

## Layout

```
backend/
  app/
    main.py          # FastAPI app, CORS, security headers, /admin static mount
    config.py        # env-driven settings
    database.py      # async engine (SQLite dev / Postgres prod), init_db
    models.py        # AdminUser, Application, License, DeviceSession, tokens, AuditLog
    schemas.py       # pydantic request/response models
    security.py      # Argon2, HMAC, JWT, server-only key generation, audit helper
    deps.py          # current_admin + first-run admin bootstrap
    rate_limit.py    # per-IP sliding-window buckets
    routers/         # admin_*, client_auth
    static/          # admin dashboard SPA (served at /admin)
  tests/             # integration test suite (SQLite)
  requirements.txt
  render.yaml        # Render blueprint
  .env.example
sdk/                 # official Python client (pip install ./sdk)
```

## Security model

- License keys minted **only server-side** via `secrets` (`XXXXX-XXXXX-...`,
  ambiguous chars excluded). Validating them is also server-side only.
- Client secret stored as **SHA-256 hash**; plaintext shown exactly once.
- **Raw HWIDs are never stored** — only HMAC-SHA256(key, hwid) with `SECRET_KEY`.
- Session tokens stored hashed, **rotated on every verify** (old token dies).
- Admin passwords via Argon2; login lockout after repeated failures; refresh
  tokens rotated and revocable.
- Audit log for every admin and auth event.
- 1 device per key by default (`MAX_ACTIVATIONS_PER_LICENSE`), HWID-bound.

## Local development

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
# optional: copy backend\.env.example to backend\.env and edit

# run the backend (admin dashboard at http://127.0.0.1:8000/admin)
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# (from backend/, or specify --app-dir backend)

# tests
..\.venv\Scripts\python.exe -m pytest tests -q
```

First run creates the admin account from `ADMIN_EMAIL` / `ADMIN_PASSWORD`
(change it immediately). In production the app refuses to boot with the default
`ADMIN_PASSWORD`.

## Deploying

1. Provision Postgres (Neon/Render/Railway) and set `DATABASE_URL`
   (`postgresql://...` works — sslmode is converted for asyncpg automatically).
2. Set `SECRET_KEY` to 32+ random chars, `ENVIRONMENT=production`,
   `COOKIE_SECURE=true`, a strong `ADMIN_PASSWORD`.
3. Deploy via `backend/render.yaml` (Render) or `uvicorn app.main:app` on any
   Python host. Migrations: `Base.metadata.create_all` runs on startup; for real
   schema evolution add Alembic.

## API (prefix `/api/v1`)

Admin (Bearer JWT from `POST /admin/login`):

- `POST /admin/refresh`, `POST /admin/logout`, `GET /admin/me`,
  `POST /admin/change-password`
- `POST|GET /admin/apps`, `PATCH|DELETE /admin/apps/{id}`,
  `POST /admin/apps/{id}/regenerate-secret`
- `POST /admin/licenses/for/{app_id}` (bulk generate), `GET /admin/licenses`,
  `GET /admin/licenses/key/{key}`, `POST /admin/licenses/{revoke|ban|reset}`
- `GET /admin/sessions?license_key=...`, `POST /admin/sessions/{id}/revoke`
- `GET /admin/audit`, `GET /admin/stats`

Client (SDK):

- `POST /auth/activate` — `{app_id, app_secret, key, hwid}` → session token
- `POST /auth/verify` — `{app_id, session_token}` → new rotating token
- `POST /auth/deactivate` — `{app_id, session_token}` → release device slot

Interactive docs: `/docs` (dev only).

## SDK

```python
from licensify import LicenseClient

with LicenseClient("https://your-server.example.com", app_id, app_secret) as c:
    sess = c.activate(key, hwid)   # HWID binds on first device
    sess = c.verify(sess.session_token)   # rotates the token each call
    c.deactivate(sess.session_token)      # release the slot
```

See `sdk/README.md`.
