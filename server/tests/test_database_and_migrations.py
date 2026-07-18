from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_production_rejects_sqlite(monkeypatch) -> None:
    monkeypatch.setenv("GANWANLE_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///unsafe.db")
    from server.settings import get_database_settings
    try:
        get_database_settings()
    except RuntimeError as error:
        assert "PostgreSQL" in str(error)
    else:
        raise AssertionError("production must reject SQLite")


def test_alembic_upgrades_empty_database(tmp_path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {
        "users", "refresh_sessions", "service_orders", "service_order_photos",
        "customer_acceptances", "audit_events", "storage_cleanup_jobs",
    } <= tables
    cleanup_columns = {
        column["name"] for column in inspect(create_engine(url)).get_columns("storage_cleanup_jobs")
    }
    assert {
        "id", "object_key", "source", "attempt_count", "last_error", "created_at", "updated_at"
    } <= cleanup_columns
