from datetime import datetime, timedelta, timezone

import jwt
import pytest

from server.security import (
    create_access_token,
    create_customer_share_token,
    decode_access_token,
    decode_customer_share_token,
    digest_refresh_token,
    generate_refresh_token,
)
from server.settings import get_auth_settings


def test_token_round_trip(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
    token = create_access_token("user-1", timedelta(minutes=5))
    assert decode_access_token(token) == "user-1"


def test_access_token_defaults_to_two_hours(monkeypatch) -> None:
    secret = "test-secret-that-is-long-enough-for-tests"
    monkeypatch.setenv("JWT_SECRET", secret)
    token = create_access_token("user-1")
    claims = jwt.decode(token, secret, algorithms=["HS256"])
    assert claims["type"] == "access"
    assert claims["exp"] - claims["iat"] == 120 * 60


def test_customer_share_token_round_trip_and_default_lifetime(monkeypatch) -> None:
    secret = "test-secret-that-is-long-enough-for-tests"
    monkeypatch.setenv("JWT_SECRET", secret)
    token = create_customer_share_token("order-1", "owner-1")
    claims = jwt.decode(token, secret, algorithms=["HS256"])

    assert decode_customer_share_token(token) == ("order-1", "owner-1")
    assert claims["type"] == "customer_share"
    assert claims["exp"] - claims["iat"] == 30 * 24 * 60 * 60


def test_customer_share_decoder_rejects_access_tokens(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
    with pytest.raises(jwt.InvalidTokenError):
        decode_customer_share_token(create_access_token("order-1"))


def test_customer_share_decoder_rejects_expired_tokens(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
    token = create_customer_share_token(
        "order-1",
        "owner-1",
        expires_delta=timedelta(seconds=-1),
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_customer_share_token(token)


def access_token_missing(secret: str, missing_claim: str) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "sub": "user-1",
        "iat": now,
        "exp": now + 300,
        "type": "access",
    }
    claims.pop(missing_claim)
    return jwt.encode(claims, secret, algorithm="HS256")


def test_decode_rejects_access_token_without_iat(monkeypatch) -> None:
    secret = "test-secret-that-is-long-enough-for-tests"
    monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(access_token_missing(secret, "iat"))


def test_decode_rejects_access_token_without_exp(monkeypatch) -> None:
    secret = "test-secret-that-is-long-enough-for-tests"
    monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(access_token_missing(secret, "exp"))


def test_refresh_tokens_are_random_and_stored_as_digests() -> None:
    first = generate_refresh_token()
    second = generate_refresh_token()
    assert first != second
    assert len(digest_refresh_token(first)) == 64
    assert first not in digest_refresh_token(first)


def test_token_lifetimes_are_fixed_security_policy(monkeypatch) -> None:
    monkeypatch.setenv("JWT_ACCESS_MINUTES", "1")
    monkeypatch.setenv("JWT_REFRESH_DAYS", "1")
    settings = get_auth_settings()
    assert settings.access_minutes == 120
    assert settings.refresh_days == 30


@pytest.mark.parametrize(
    ("app_id", "app_secret", "jwt_secret"),
    [("", "secret", "x" * 32), ("app", "", "x" * 32), ("app", "secret", "too-short")],
)
def test_production_rejects_missing_or_weak_auth_secrets(monkeypatch, app_id, app_secret, jwt_secret) -> None:
    monkeypatch.setenv("GANWANLE_ENV", "production")
    monkeypatch.setenv("WECHAT_APP_ID", app_id)
    monkeypatch.setenv("WECHAT_APP_SECRET", app_secret)
    monkeypatch.setenv("JWT_SECRET", jwt_secret)
    with pytest.raises(RuntimeError):
        get_auth_settings()
