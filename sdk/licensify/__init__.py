"""LicenseServer official Python client.

The server is the sole authority for license validity. This SDK only forwards
requests; it never mints or validates keys locally, so decompiling the app
cannot bypass the server.
"""

from .client import (
    LicenseClient,
    LicenseError,
    LicenseSession,
    SessionExpired,
)

__all__ = [
    "LicenseClient",
    "LicenseError",
    "LicenseSession",
    "SessionExpired",
]

__version__ = "1.1.0"
