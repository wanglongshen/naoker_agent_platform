from datetime import datetime, timedelta, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import get_settings

ph = PasswordHasher()
settings = get_settings()


class TokenPayload(BaseModel):
    sub: str
    username: str
    iat: datetime
    exp: datetime


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("密码长度不能少于 8 位")
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise ValueError("密码必须同时包含字母和数字")


def create_access_token(user) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    claims = {
        "sub": str(user.id),
        "username": user.username,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> TokenPayload:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    try:
        return TokenPayload(
            sub=payload["sub"],
            username=payload["username"],
            iat=datetime.fromtimestamp(payload["iat"], tz=UTC),
            exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except KeyError as exc:
        raise JWTError(f"Token missing required claim: {exc.args[0]}") from exc

# --- DSH connector platform token (TTL-scoped, sub=user_id, scope=dsh-connector) ---



# --- DSH connector platform token (TTL-scoped, sub=user_id, scope=dsh-connector) ---

def mint_platform_token(user_id: str, ttl_seconds: int) -> str:
    """Platform-internal short-lived token used by the DSH connector plugin via X-Platform-Token header."""
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "scope": "dsh-connector",
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_platform_token(token: str) -> str | None:
    """Return user_id; None when invalid/expired/not a connector token."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except (JWTError, ValueError):
        return None
    if payload.get("scope") != "dsh-connector":
        return None
    return payload.get("sub")
