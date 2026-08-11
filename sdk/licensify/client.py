"""HTTP client for the LicenseServer backend."""

import ssl
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

__all__ = ["LicenseClient", "LicenseError", "LicenseSession", "SessionExpired"]


class LicenseError(Exception):
    """The server rejected the operation. Carries the HTTP status and reason."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


class SessionExpired(LicenseError):
    """The session token is invalid, expired, or was rotated by a later verify."""


@dataclass(frozen=True)
class LicenseSession:
    """A live server session. ``session_token`` rotates on every ``verify()``."""

    session_token: str
    expires_in: int
    expires_at: Optional[str]
    license_key: Optional[str] = None
    app_id: Optional[str] = None

    @property
    def valid(self) -> bool:
        return True


class LicenseClient:
    def __init__(
        self,
        base_url: str,
        app_id: str,
        app_secret: str,
        timeout: float = 10.0,
        pinned_ca: Optional[str] = None,
    ) -> None:
        """LicenseClient for the LicenseServer backend.

        ``base_url`` is the HTTPS endpoint of your server. Plain ``http://`` is
        refused unless the host is localhost (dev/testing only).

        ``pinned_ca`` optionally points at a PEM bundle containing the
        certificate(s) you trust. When set, the client will ONLY trust a server
        presenting a certificate chaining to that bundle — a MITM or spoofed
        server is rejected even if it has a valid public CA cert. This is the
        defense against an attacker re-pointing your app at a fake server.
        """
        scheme = urlparse(base_url).scheme.lower()
        host = urlparse(base_url).hostname or ""
        if scheme != "https" and host not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("base_url must use https (http is only allowed for localhost)")
        if pinned_ca:
            ctx = ssl.create_default_context(cafile=pinned_ca)
            ctx.verify_mode = ssl.CERT_REQUIRED
        else:
            ctx = ssl.create_default_context()
        self._base = base_url.rstrip("/")
        self._app_id = app_id
        self._app_secret = app_secret
        self._client = httpx.Client(base_url=self._base, timeout=timeout, verify=ctx)

    # ------------------------------------------------------------- helpers
    def _raise(self, resp: httpx.Response) -> None:
        detail = "request failed"
        try:
            data = resp.json()
            detail = data.get("detail", detail) if isinstance(data, dict) else str(data)
        except ValueError:
            pass
        exc = SessionExpired if resp.status_code == 401 else LicenseError
        raise exc(resp.status_code, detail)

    # ------------------------------------------------------------- auth
    def activate(self, key: str, hwid: str) -> LicenseSession:
        """Activate a license key for this device.

        Binds the HWID server-side (first device wins). Raises ``LicenseError``
        on an invalid/expired/banned key or when max activations are reached.
        """
        resp = self._client.post(
            "/api/v1/auth/activate",
            json={"app_id": self._app_id, "app_secret": self._app_secret, "key": key, "hwid": hwid},
        )
        if resp.status_code != 200:
            self._raise(resp)
        data = resp.json()
        return LicenseSession(
            session_token=data["session_token"],
            expires_in=data["expires_in"],
            expires_at=data.get("expires_at"),
        )

    def verify(self, session_token: str) -> LicenseSession:
        """Confirm the session is still valid.

        The server rotates the session token on every call: the old token dies
        and the returned ``session_token`` must be used next time. If the key
        was revoked/banned/expired, ``SessionExpired`` is raised.
        """
        resp = self._client.post(
            "/api/v1/auth/verify",
            json={"app_id": self._app_id, "session_token": session_token},
        )
        if resp.status_code != 200:
            self._raise(resp)
        data = resp.json()
        return LicenseSession(
            session_token=data["session_token"],
            expires_in=data["expires_in"],
            expires_at=data.get("expires_at"),
            license_key=data.get("license_key"),
            app_id=data.get("app_id"),
        )

    def deactivate(self, session_token: str) -> None:
        """End the session and release the device slot (unbinds the HWID)."""
        resp = self._client.post(
            "/api/v1/auth/deactivate",
            json={"app_id": self._app_id, "session_token": session_token},
        )
        if resp.status_code != 204:
            self._raise(resp)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LicenseClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
