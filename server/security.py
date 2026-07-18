from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .settings import AuthSettings, get_auth_settings

ALGORITHM = "HS256"
INVALID_AUTH_DETAIL = "未登录或登录已失效"
bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
    settings: Optional[AuthSettings] = None,
) -> str:
    auth_settings = settings or get_auth_settings()
    now = int(datetime.now(timezone.utc).timestamp())
    lifetime = expires_delta or timedelta(minutes=auth_settings.access_minutes)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + int(lifetime.total_seconds()),
        "type": "access",
    }
    return jwt.encode(payload, auth_settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Optional[AuthSettings] = None) -> str:
    auth_settings = settings or get_auth_settings()
    claims = jwt.decode(
        token,
        auth_settings.jwt_secret,
        algorithms=[ALGORITHM],
        options={"require": ["sub", "iat", "exp", "type"]},
    )
    subject = claims.get("sub")
    if claims.get("type") != "access" or not isinstance(subject, str) or not subject:
        raise jwt.InvalidTokenError("invalid access token")
    return subject


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def digest_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_AUTH_DETAIL)
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_AUTH_DETAIL) from None
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_AUTH_DETAIL)
    return user
