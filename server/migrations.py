from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


ORDER_COLUMNS = {
    "transcription_status": "VARCHAR(32) NOT NULL DEFAULT 'not_started'",
    "transcription_error": "TEXT",
    "asr_request_id": "VARCHAR(100)",
    "audio_duration_ms": "INTEGER",
    "report_generation_status": "VARCHAR(32) NOT NULL DEFAULT 'not_started'",
    "report_generation_error": "TEXT",
    "report_model": "VARCHAR(200)",
    "report_generated_at": "DATETIME",
}


def migrate(engine: Engine) -> None:
    """Apply small, repeatable SQLite migrations without replacing existing data."""
    existing = {column["name"] for column in inspect(engine).get_columns("service_orders")}
    with engine.begin() as connection:
        for name, definition in ORDER_COLUMNS.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE service_orders ADD COLUMN {name} {definition}"))
        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS service_orders_transcription_status_insert
            BEFORE INSERT ON service_orders
            WHEN NEW.transcription_status NOT IN ('not_started','processing','succeeded','failed')
            BEGIN SELECT RAISE(ABORT, 'invalid transcription_status'); END
        """))
        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS service_orders_transcription_status_update
            BEFORE UPDATE OF transcription_status ON service_orders
            WHEN NEW.transcription_status NOT IN ('not_started','processing','succeeded','failed')
            BEGIN SELECT RAISE(ABORT, 'invalid transcription_status'); END
        """))
        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS service_orders_report_generation_status_insert
            BEFORE INSERT ON service_orders
            WHEN NEW.report_generation_status NOT IN ('not_started','processing','succeeded','failed')
            BEGIN SELECT RAISE(ABORT, 'invalid report_generation_status'); END
        """))
        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS service_orders_report_generation_status_update
            BEFORE UPDATE OF report_generation_status ON service_orders
            WHEN NEW.report_generation_status NOT IN ('not_started','processing','succeeded','failed')
            BEGIN SELECT RAISE(ABORT, 'invalid report_generation_status'); END
        """))
