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
    inspector = inspect(create_engine(url))
    tables = set(inspector.get_table_names())
    assert {
        "users", "refresh_sessions", "service_orders", "service_order_photos",
        "customer_acceptances", "audit_events", "storage_cleanup_jobs",
    } <= tables
    cleanup_columns = {
        column["name"] for column in inspector.get_columns("storage_cleanup_jobs")
    }
    assert {
        "id", "object_key", "source", "attempt_count", "last_error", "created_at", "updated_at"
    } <= cleanup_columns
    unique_columns = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("storage_cleanup_jobs")
    }
    index_names = {index["name"] for index in inspector.get_indexes("storage_cleanup_jobs")}
    assert ("object_key",) in unique_columns
    assert "ix_storage_cleanup_jobs_object_key" not in index_names
