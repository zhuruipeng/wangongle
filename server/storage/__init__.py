from functools import lru_cache
from pathlib import Path

from ..settings import get_auth_settings, get_storage_settings
from .base import StorageBackend
from .cos import CosStorage
from .keys import ParsedObjectKey, build_object_key, parse_object_key
from .local import LocalStorage


@lru_cache
def get_storage() -> StorageBackend:
    settings = get_storage_settings()
    if settings.backend == "local":
        return LocalStorage(Path(settings.local_root), signing_secret=get_auth_settings().jwt_secret)
    return CosStorage(settings)


__all__ = [
    "CosStorage",
    "LocalStorage",
    "ParsedObjectKey",
    "StorageBackend",
    "build_object_key",
    "get_storage",
    "parse_object_key",
]
