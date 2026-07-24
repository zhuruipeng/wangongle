from alembic import command
from alembic.config import Config
from io import StringIO
import pytest
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


def test_production_rejects_remote_postgresql_without_echoing_url(monkeypatch) -> None:
    url = "postgresql+psycopg://service:should-not-be-echoed@db.example.com/ganwanle"
    monkeypatch.setenv("GANWANLE_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", url)
    from server.settings import get_database_settings

    with pytest.raises(RuntimeError) as error:
        get_database_settings()

    assert str(error.value) == "Production requires a loopback PostgreSQL database"
    assert url not in str(error.value)
    assert "should-not-be-echoed" not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://service:password@127.0.0.1/ganwanle",
        "postgresql+psycopg://service:password@localhost/ganwanle",
        "postgresql+psycopg://service:password@[::1]/ganwanle",
    ],
)
def test_production_accepts_loopback_psycopg_urls(monkeypatch, url: str) -> None:
    monkeypatch.setenv("GANWANLE_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", url)
    from server.settings import get_database_settings

    assert get_database_settings().url == url


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
    order_columns = {
        column["name"]: column for column in inspector.get_columns("service_orders")
    }
    assert order_columns["audio_delete_after"]["nullable"] is True
    assert order_columns["transcription_claim_token"]["nullable"] is True
    assert order_columns["service_location_name"]["nullable"] is True
    assert order_columns["service_latitude"]["nullable"] is True
    assert order_columns["service_longitude"]["nullable"] is True
    current_output = StringIO()
    command.current(Config("alembic.ini", stdout=current_output))
    assert "0005 (head)" in current_output.getvalue()
