import logging

from sqlalchemy import select

from server.models import AuditEvent, RefreshSession, User


def login(client, monkeypatch, *, openid="openid-a"):
    monkeypatch.setattr(
        "server.routers.auth.exchange_code",
        lambda code, settings: {"openid": openid, "unionid": None},
    )
    return client.post("/api/v1/auth/wechat", json={"code": "valid-code"})


def test_wechat_login_auto_registers(client, monkeypatch) -> None:
    response = login(client, monkeypatch)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "technician"
    assert response.json()["user"]["profile_complete"] is False
    assert response.json()["token_type"] == "bearer"
    assert response.json()["expires_in"] == 7200


def test_repeat_login_reuses_user(client, monkeypatch, db_session) -> None:
    first = login(client, monkeypatch)
    second = login(client, monkeypatch)
    assert second.status_code == 200
    assert second.json()["user"]["id"] == first.json()["user"]["id"]
    assert len(db_session.scalars(select(User)).all()) == 1


def test_invalid_wechat_code_returns_sanitized_error(client, monkeypatch, caplog) -> None:
    from server.services.wechat_auth import WeChatLoginError

    temporary_code = "temporary-wechat-code-never-log"

    def fail(_code, _settings):
        raise WeChatLoginError("微信登录失败")

    monkeypatch.setattr("server.routers.auth.exchange_code", fail)
    with caplog.at_level(logging.INFO):
        response = client.post("/api/v1/auth/wechat", json={"code": temporary_code})
    assert response.status_code == 502
    assert response.json() == {"detail": "微信登录失败"}
    assert temporary_code not in caplog.text


def test_auth_codes_tokens_and_secrets_never_appear_in_logs(client, monkeypatch, caplog) -> None:
    code = "temporary-code-for-redaction-check"
    monkeypatch.setattr(
        "server.routers.auth.exchange_code",
        lambda supplied_code, settings: {"openid": "openid-log-check", "unionid": None},
    )
    with caplog.at_level(logging.INFO):
        login_response = client.post("/api/v1/auth/wechat", json={"code": code})
        tokens = login_response.json()
        client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert code not in caplog.text
    assert tokens["access_token"] not in caplog.text
    assert tokens["refresh_token"] not in caplog.text
    assert "test-app-secret" not in caplog.text


def test_profile_update_trims_name(client, monkeypatch) -> None:
    auth = login(client, monkeypatch).json()
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    response = client.patch(
        "/api/v1/auth/me/profile",
        headers=headers,
        json={"technician_name": "  王师傅  "},
    )
    assert response.status_code == 200
    assert response.json()["technician_name"] == "王师傅"
    assert response.json()["profile_complete"] is True
    assert client.get("/api/v1/auth/me", headers=headers).json()["profile_complete"] is True


def test_profile_name_length_is_checked_after_trimming(client, monkeypatch) -> None:
    auth = login(client, monkeypatch).json()
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    name = "师" * 100
    response = client.patch(
        "/api/v1/auth/me/profile",
        headers=headers,
        json={"technician_name": f"  {name}  "},
    )
    assert response.status_code == 200
    assert response.json()["technician_name"] == name


def test_refresh_rotates_and_rejects_replay(client, monkeypatch, db_session) -> None:
    original = login(client, monkeypatch).json()["refresh_token"]
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != original
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert replay.status_code == 401
    sessions = db_session.scalars(select(RefreshSession).order_by(RefreshSession.created_at)).all()
    assert len(sessions) == 2
    assert sessions[0].revoked_at is not None
    assert sessions[1].revoked_at is None


def test_logout_revokes_refresh_token(client, monkeypatch) -> None:
    refresh_token = login(client, monkeypatch).json()["refresh_token"]
    response = client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert response.status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token}).status_code == 401


def test_inactive_user_is_rejected(client, monkeypatch, db_session) -> None:
    auth = login(client, monkeypatch).json()
    user = db_session.get(User, auth["user"]["id"])
    user.status = "inactive"
    db_session.commit()
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
    )
    assert response.status_code == 401


def test_missing_bearer_token_is_rejected(client) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_login_rate_limit_is_twenty_requests_per_five_minutes(client, monkeypatch) -> None:
    calls = 0

    def exchange(_code, _settings):
        nonlocal calls
        calls += 1
        return {"openid": "openid-rate-limit", "unionid": None}

    monkeypatch.setattr("server.routers.auth.exchange_code", exchange)
    for _ in range(20):
        assert client.post("/api/v1/auth/wechat", json={"code": "valid-code"}).status_code == 200
    response = client.post("/api/v1/auth/wechat", json={"code": "valid-code"})
    assert response.status_code == 429
    assert calls == 20


def test_refresh_rate_limit_uses_digest_prefix(client, monkeypatch) -> None:
    token = login(client, monkeypatch).json()["refresh_token"]
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": token}).status_code == 200
    for _ in range(29):
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": token}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": token}).status_code == 429


def test_request_id_is_returned_and_saved_on_audit(client, monkeypatch, db_session) -> None:
    monkeypatch.setattr(
        "server.routers.auth.exchange_code",
        lambda code, settings: {"openid": "openid-a", "unionid": None},
    )
    response = client.post(
        "/api/v1/auth/wechat",
        json={"code": "valid-code"},
        headers={"X-Request-ID": "request-123"},
    )
    assert response.headers["X-Request-ID"] == "request-123"
    event = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == "wechat_login"))
    assert event is not None
    assert event.request_id == "request-123"


def test_invalid_request_id_is_replaced(client) -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "contains spaces"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "contains spaces"
    assert len(response.headers["X-Request-ID"]) == 36


def test_unhandled_errors_are_sanitized_in_production(client, caplog, monkeypatch) -> None:
    secret = "secret-that-must-never-be-logged"
    monkeypatch.setenv("GANWANLE_ENV", "production")

    @client.app.get("/_test/boom")
    def boom():
        raise RuntimeError(secret)

    with caplog.at_level(logging.ERROR):
        response = client.get("/_test/boom", headers={"X-Request-ID": "production-request"})
    assert response.status_code == 500
    assert response.json() == {"detail": "服务暂时不可用", "request_id": "production-request"}
    assert secret not in caplog.text


def test_wechat_exchange_returns_only_identity(monkeypatch) -> None:
    from server.services.wechat_auth import exchange_code
    from server.settings import AuthSettings

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"openid": "openid-a", "unionid": "unionid-a", "session_key": "never-return"}

    monkeypatch.setattr("server.services.wechat_auth.httpx.get", lambda *args, **kwargs: Response())
    identity = exchange_code("temporary-code", AuthSettings("app", "secret", "x" * 32))
    assert identity == {"openid": "openid-a", "unionid": "unionid-a"}


def test_wechat_exchange_sanitizes_upstream_errors(monkeypatch) -> None:
    from server.services.wechat_auth import WeChatLoginError, exchange_code
    from server.settings import AuthSettings

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"errcode": 40029, "errmsg": "sensitive-upstream-message"}

    monkeypatch.setattr("server.services.wechat_auth.httpx.get", lambda *args, **kwargs: Response())
    try:
        exchange_code("temporary-code", AuthSettings("app", "secret", "x" * 32))
    except WeChatLoginError as error:
        assert str(error) == "微信登录失败"
        assert "sensitive-upstream-message" not in str(error)
    else:
        raise AssertionError("WeChat errors must be rejected")
