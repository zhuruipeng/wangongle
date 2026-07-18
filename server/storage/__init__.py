from functools import lru_cache
from pathlib import Path
import re
from uuid import uuid4

from ..settings import get_auth_settings, get_storage_settings
from .base import StorageBackend
from .cos import CosStorage
from .local import LocalStorage

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_segment(value: str) -> str:
    if not value or not _SAFE_SEGMENT.fullmatch(value):
        raise ValueError("object key segment contains unsupported characters")
    return value


def build_object_key(
    environment: str,
    user_id: str,
    order_id: str,
    category: str,
    suffix: str,
) -> str:
    environment = _safe_segment(environment)
    user_id = _safe_segment(user_id)
    order_id = _safe_segment(order_id)
    if category not in {"photos", "signatures", "audio-pending", "audio-expiring"}:
        raise ValueError("unsupported object category")
    if not re.fullmatch(r"\.[a-z0-9]+", suffix):
        raise ValueError("unsupported object suffix")
    filename = f"{uuid4().hex}{suffix}"
    if category.startswith("audio-"):
        return f"{environment}/{category}/users/{user_id}/orders/{order_id}/{filename}"
    return f"{environment}/users/{user_id}/orders/{order_id}/{category}/{filename}"


@lru_cache
def get_storage() -> StorageBackend:
    settings = get_storage_settings()
    if settings.backend == "local":
        return LocalStorage(Path(settings.local_root), signing_secret=get_auth_settings().jwt_secret)
    return CosStorage(settings)


__all__ = [
    "CosStorage",
    "LocalStorage",
    "StorageBackend",
    "build_object_key",
    "get_storage",
]
