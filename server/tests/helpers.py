import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import server.models
from server.database import Base, get_db


class IsolatedTestClient(TestClient):
    def __init__(
        self,
        application: Any,
        environment: dict[str, str],
        engine: Engine,
        storage_directory: TemporaryDirectory,
    ) -> None:
        super().__init__(application)
        self._environment = environment
        self._engine = engine
        self._storage_directory = storage_directory

    def request(self, *args: Any, **kwargs: Any):
        with patch.dict(os.environ, self._environment, clear=False):
            return super().request(*args, **kwargs)

    def close(self) -> None:
        try:
            super().close()
        finally:
            from server.storage import get_storage

            get_storage.cache_clear()
            self._engine.dispose()
            self._storage_directory.cleanup()


def build_test_client() -> TestClient:
    storage_directory = TemporaryDirectory(prefix="ganwanle-legacy-test-")
    environment = {
        "GANWANLE_ENV": "test",
        "JWT_SECRET": "legacy-test-secret-that-is-long-enough",
        "STORAGE_BACKEND": "local",
        "LOCAL_STORAGE_ROOT": str(Path(storage_directory.name) / "private-storage"),
    }
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with testing_session() as session:
            yield session

    with patch.dict(os.environ, environment, clear=False):
        from server.main import create_app
        from server.storage import get_storage

        get_storage.cache_clear()
        application = create_app()
    application.state.redis = None
    application.dependency_overrides[get_db] = override_get_db
    return IsolatedTestClient(application, environment, engine, storage_directory)
