from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from server.database import Base, get_db


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
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("GANWANLE_ENV", "test")
    monkeypatch.setenv("WECHAT_APP_ID", "test-app-id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-for-tests")

    from server.main import create_app

    application = create_app()
    application.state.redis = FakeRedis()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    application.dependency_overrides[get_db] = override_get_db
    with TestClient(application, raise_server_exceptions=False) as test_client:
        yield test_client
