from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditEvent, RefreshSession, User
from ..schemas import (
    AuthResponse,
    AuthUserResponse,
    ProfileUpdateRequest,
    RefreshTokenRequest,
    TokenPairResponse,
    WeChatLoginRequest,
)
from ..security import INVALID_AUTH_DETAIL, create_access_token, digest_refresh_token, generate_refresh_token, get_current_user
from ..services.rate_limit import check_rate_limit
from ..services.wechat_auth import WeChatLoginError, exchange_code
from ..settings import AuthSettings, RedisSettings, get_auth_settings, get_redis_settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_expired(value: datetime, now: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= now


def user_response(user: User) -> AuthUserResponse:
    return AuthUserResponse(
        id=user.id,
        role=user.role,
        technician_name=user.technician_name,
        profile_complete=bool(user.technician_name and user.technician_name.strip()),
    )


def create_session(db: Session, user: User, settings: AuthSettings, now: datetime) -> tuple[str, RefreshSession]:
    refresh_token = generate_refresh_token()
    refresh_session = RefreshSession(
        user_id=user.id,
        token_digest=digest_refresh_token(refresh_token),
        expires_at=now + timedelta(days=settings.refresh_days),
    )
    db.add(refresh_session)
    return refresh_token, refresh_session


def add_audit(
    db: Session,
    request: Request,
    event_type: str,
    outcome: str,
    user: Optional[User] = None,
) -> None:
    db.add(AuditEvent(
        user_id=user.id if user else None,
        resource_type="user",
        resource_id=user.id if user else "unknown",
        request_id=request.state.request_id,
        event_type=event_type,
        outcome=outcome,
    ))


def enforce_limit(request: Request, key: str, limit: int, window_seconds: int) -> None:
    if not check_rate_limit(request.app.state.redis, key, limit, window_seconds):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="请求过于频繁")


@router.post("/wechat", response_model=AuthResponse)
def wechat_login(payload: WeChatLoginRequest, request: Request, db: Session = Depends(get_db)) -> AuthResponse:
    auth_settings = get_auth_settings()
    redis_settings: RedisSettings = get_redis_settings()
    client_ip = request.client.host if request.client else "unknown"
    enforce_limit(request, f"{redis_settings.key_prefix}:rate:login:{client_ip}", 20, 5 * 60)
    try:
        identity = exchange_code(payload.code, auth_settings)
    except WeChatLoginError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="微信登录失败") from None

    user = db.scalar(select(User).where(User.openid == identity["openid"]))
    if user is None:
        try:
            with db.begin_nested():
                user = User(openid=identity["openid"], unionid=identity["unionid"])
                db.add(user)
                db.flush()
        except IntegrityError:
            user = db.scalar(select(User).where(User.openid == identity["openid"]))
            if user is None:
                raise
    elif identity["unionid"] and user.unionid != identity["unionid"]:
        user.unionid = identity["unionid"]

    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_AUTH_DETAIL)
    now = utc_now()
    refresh_token, _ = create_session(db, user, auth_settings, now)
    add_audit(db, request, "wechat_login", "succeeded", user)
    db.commit()
    return AuthResponse(
        access_token=create_access_token(user.id, settings=auth_settings),
        refresh_token=refresh_token,
        expires_in=auth_settings.access_minutes * 60,
        user=user_response(user),
    )


@router.post("/refresh", response_model=TokenPairResponse)
def refresh_tokens(payload: RefreshTokenRequest, request: Request, db: Session = Depends(get_db)) -> TokenPairResponse:
    auth_settings = get_auth_settings()
    redis_settings = get_redis_settings()
    digest = digest_refresh_token(payload.refresh_token)
    enforce_limit(request, f"{redis_settings.key_prefix}:rate:refresh:{digest[:16]}", 30, 5 * 60)
    session = db.scalar(
        select(RefreshSession)
        .where(RefreshSession.token_digest == digest)
        .with_for_update()
    )
    now = utc_now()
    if session is None or session.revoked_at is not None or is_expired(session.expires_at, now):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_AUTH_DETAIL)
    user = db.get(User, session.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_AUTH_DETAIL)
    session.revoked_at = now
    new_refresh_token, _ = create_session(db, user, auth_settings, now)
    add_audit(db, request, "token_refresh", "succeeded", user)
    db.commit()
    return TokenPairResponse(
        access_token=create_access_token(user.id, settings=auth_settings),
        refresh_token=new_refresh_token,
        expires_in=auth_settings.access_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshTokenRequest, request: Request, db: Session = Depends(get_db)) -> Response:
    digest = digest_refresh_token(payload.refresh_token)
    session = db.scalar(
        select(RefreshSession)
        .where(RefreshSession.token_digest == digest)
        .with_for_update()
    )
    user = db.get(User, session.user_id) if session else None
    if session and session.revoked_at is None:
        session.revoked_at = utc_now()
    add_audit(db, request, "logout", "succeeded", user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=AuthUserResponse)
def get_me(user: User = Depends(get_current_user)) -> AuthUserResponse:
    return user_response(user)


@router.patch("/me/profile", response_model=AuthUserResponse)
def update_profile(
    payload: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuthUserResponse:
    user.technician_name = payload.technician_name
    db.commit()
    db.refresh(user)
    return user_response(user)
