import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from .config import settings
from .database import SessionLocal, init_db
from .deps import bootstrap_admin
from .routers import admin_apps, admin_audit, admin_auth, admin_licenses, admin_sessions, client_auth

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("licensing")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with SessionLocal() as db:
        await bootstrap_admin(db)
    log.info("Database initialized; admin bootstrap complete")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

app.include_router(admin_auth.router, prefix=settings.API_PREFIX)
app.include_router(admin_apps.router, prefix=settings.API_PREFIX)
app.include_router(admin_licenses.router, prefix=settings.API_PREFIX)
app.include_router(admin_sessions.router, prefix=settings.API_PREFIX)
app.include_router(admin_audit.router, prefix=settings.API_PREFIX)
app.include_router(client_auth.router, prefix=settings.API_PREFIX)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/admin", StaticFiles(directory=str(STATIC_DIR), html=True), name="admin")


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "app": settings.APP_NAME}


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=404, content={"detail": "Not found"})
