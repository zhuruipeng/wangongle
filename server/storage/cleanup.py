from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import StorageCleanupJob


SAFE_DELETE_ERROR = "storage delete failed"


def enqueue_storage_cleanup(db: Session, object_key: str, source: str) -> None:
    bind = db.get_bind()
    with Session(bind=bind, expire_on_commit=False) as cleanup_db:
        existing = cleanup_db.scalar(
            select(StorageCleanupJob).where(StorageCleanupJob.object_key == object_key)
        )
        if existing is not None:
            return
        cleanup_db.add(StorageCleanupJob(object_key=object_key, source=source))
        try:
            cleanup_db.commit()
        except IntegrityError:
            cleanup_db.rollback()


def delete_or_enqueue(
    db: Session,
    storage: Any,
    object_key: str,
    source: str,
) -> None:
    try:
        storage.delete(object_key)
    except Exception:
        enqueue_storage_cleanup(db, object_key, source)


def retry_storage_cleanup(
    db: Session,
    storage: Any,
    limit: int = 100,
) -> dict[str, int]:
    jobs = db.scalars(
        select(StorageCleanupJob)
        .order_by(StorageCleanupJob.created_at, StorageCleanupJob.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    succeeded = 0
    failed = 0
    for job in jobs:
        try:
            storage.delete(job.object_key)
        except Exception:
            job.attempt_count += 1
            job.last_error = SAFE_DELETE_ERROR
            job.updated_at = datetime.now(timezone.utc)
            failed += 1
        else:
            db.delete(job)
            succeeded += 1
    db.commit()
    return {"succeeded": succeeded, "failed": failed}
