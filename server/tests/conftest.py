from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from server.database import Base, get_db
from server.models import User
from server.security import create_access_token


ORDER_PAYLOAD = {
    "order_no": "ORDER-001",
    "company_name": "测试服务公司",
    "customer_name": "敏感客户姓名",
    "customer_phone": "13800000000",
    "service_address": "敏感服务地址",
    "service_type": "空调安装",
    "status": "in_progress",
}


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def eval(self, _script: str, _number_of_keys: int, key: str, _window: int) -> int:
        count = self.counts.get(key, 0) + 1
        self.counts[key] = count
        return count


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with testing_session() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("GANWANLE_ENV", "test")
    monkeypatch.setenv("WECHAT_APP_ID", "test-app-id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "private-storage"))

    from server.main import create_app
    from server.storage import get_storage

    get_storage.cache_clear()
    application = create_app()
    application.state.redis = FakeRedis()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    application.dependency_overrides[get_db] = override_get_db
    with TestClient(application, raise_server_exceptions=False) as test_client:
        yield test_client
    get_storage.cache_clear()


@pytest.fixture
def auth_headers(client, db_session: Session) -> Callable[..., dict[str, str]]:
    def create_headers(openid: str, technician_name: Optional[str] = None) -> dict[str, str]:
        user = User(
            openid=openid,
            technician_name=technician_name if technician_name is not None else f"师傅-{openid}",
        )
        db_session.add(user)
        db_session.commit()
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    return create_headers


@pytest.fixture
def create_order(client) -> Callable[..., dict[str, Any]]:
    def create(headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
        payload = {**ORDER_PAYLOAD, **overrides}
        response = client.post("/api/v1/service-orders", headers=headers, json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    return create
