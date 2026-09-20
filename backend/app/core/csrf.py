from datetime import datetime, timedelta, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from fastapi import Depends, Request
from jose import jwt
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.security import decode_access_token

CSRF_HEADER = "X-CSRF-Token"

settings = get_settings()


class CsrfTokenPayload(BaseModel):
    sub: str
    iat: datetime
    exp: datetime


def issue_csrf_token(user_id: str) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=60)
    claims = {"sub": user_id, "iat": now, "exp": expire, "purpose": "csrf"}
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def _validate_origin(request: Request) -> None:
    allowed_origins = [origin.strip() for origin in settings.cors_origins.split(",")]
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not any(origin.startswith(allowed) or origin == allowed for allowed in allowed_origins):
        raise ApiError(
            status_code=403,
            code="CSRF_VALIDATION_FAILED",
            message="Invalid request origin",
        )


async def require_csrf(
    request: Request,
) -> None:
    csrf_header_value = request.headers.get(CSRF_HEADER)
    if not csrf_header_value:
        raise ApiError(
            status_code=403,
            code="CSRF_VALIDATION_FAILED",
            message="Missing CSRF token header",
        )

    _validate_origin(request)

    try:
        payload = jwt.decode(csrf_header_value, settings.jwt_secret, algorithms=["HS256"])
    except Exception:
        raise ApiError(
            status_code=403,
            code="CSRF_VALIDATION_FAILED",
            message="Invalid CSRF token",
        )

    if payload.get("purpose") != "csrf":
        raise ApiError(
            status_code=403,
            code="CSRF_VALIDATION_FAILED",
            message="Invalid CSRF token purpose",
        )

    token_sub = payload.get("sub")
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise ApiError(
            status_code=403,
            code="CSRF_VALIDATION_FAILED",
            message="Missing access token",
        )

    try:
        access_payload = decode_access_token(access_token)
    except Exception:
        raise ApiError(
            status_code=403,
            code="CSRF_VALIDATION_FAILED",
            message="Invalid access token",
        )

    if token_sub != access_payload.sub:
        raise ApiError(
            status_code=403,
            code="CSRF_VALIDATION_FAILED",
            message="CSRF token does not match current user",
        )
