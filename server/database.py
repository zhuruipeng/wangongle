from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .settings import get_database_settings

SERVER_DIR = Path(__file__).resolve().parent
DATA_DIR = SERVER_DIR / "data"
UPLOAD_DIR = SERVER_DIR / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

database_settings = get_database_settings()

engine_options = {"pool_pre_ping": True}
if database_settings.url.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
else:
    engine_options["pool_size"] = database_settings.pool_size
    engine_options["max_overflow"] = database_settings.max_overflow

engine = create_engine(database_settings.url, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
