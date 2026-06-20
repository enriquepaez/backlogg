"""Admin authentication dependency.

Verifies the X-API-Key header against the ADMIN_API_KEY environment variable.

Rules:
- ADMIN_API_KEY not set (empty string) → 503 Service Unavailable
- Header missing or value does not match → 401 Unauthorized
- Header matches → allow request through
- The key value is never included in log output or error response bodies.
"""

from fastapi import Header, HTTPException

from backlogg.core.config import settings


async def verify_api_key(x_api_key: str = Header(default="")) -> None:
    """FastAPI dependency that enforces X-API-Key authentication.

    Raises:
        HTTPException 503: ADMIN_API_KEY is not configured.
        HTTPException 401: Header is missing or value is incorrect.
    """
    configured_key = settings.ADMIN_API_KEY

    if not configured_key:
        raise HTTPException(
            status_code=503,
            detail="Admin API key is not configured.",
        )

    if not x_api_key or x_api_key != configured_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-API-Key header.",
        )
