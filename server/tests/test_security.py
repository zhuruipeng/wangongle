from datetime import timedelta

import jwt
import pytest

from server.security import create_access_token, decode_access_token, digest_refresh_token, generate_refresh_token
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


def test_refresh_tokens_are_random_and_stored_as_digests() -> None:
    first = generate_refresh_token()
    second = generate_refresh_token()
    assert first != second
    assert len(digest_refresh_token(first)) == 64
    assert first not in digest_refresh_token(first)


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
