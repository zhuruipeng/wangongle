from hashlib import sha256
import hmac
import os
from pathlib import Path
import secrets
import shutil
import time
from typing import BinaryIO, Optional
from urllib.parse import quote

from .keys import parse_object_key


LOCAL_FILE_ROUTE = "/api/v1/service-orders/private-files"
_PROCESS_SIGNING_SECRET = secrets.token_bytes(32)


class LocalStorage:
    def __init__(self, root: Path, signing_secret: Optional[str] = None) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        configured_secret = (signing_secret or os.getenv("JWT_SECRET", "")).strip()
        self._signing_secret = (
            configured_secret.encode("utf-8")
            if configured_secret
            else _PROCESS_SIGNING_SECRET
        )

    def resolve_key(self, key: str) -> Path:
        parsed = parse_object_key(key)
        target = (self.root / parsed.key).resolve()
        if target == self.root or self.root not in target.parents:
            raise ValueError("invalid storage key")
        return target

    def put(self, key: str, stream: BinaryIO, content_type: str) -> None:
        del content_type
        target = self.resolve_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            shutil.copyfileobj(stream, output)

    def download_to(self, key: str, target: Path) -> None:
        source = self.resolve_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def delete(self, key: str) -> None:
        self.resolve_key(key).unlink(missing_ok=True)

    def copy(self, source_key: str, target_key: str) -> None:
        source = self.resolve_key(source_key)
        target = self.resolve_key(target_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def move(self, source_key: str, target_key: str) -> None:
        source = self.resolve_key(source_key)
        target = self.resolve_key(target_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)

    def exists(self, key: str) -> bool:
        return self.resolve_key(key).is_file()

    def _signature(self, key: str, expires: int) -> str:
        canonical_key = parse_object_key(key).key
        payload = f"{canonical_key}:{expires}".encode("utf-8")
        return hmac.new(self._signing_secret, payload, sha256).hexdigest()

    def presigned_get_url(self, key: str, expires_seconds: int) -> str:
        canonical_key = parse_object_key(key).key
        self.resolve_key(canonical_key)
        expires = int(time.time()) + expires_seconds
        signature = self._signature(canonical_key, expires)
        return f"{LOCAL_FILE_ROUTE}/{quote(canonical_key, safe='/')}?expires={expires}&signature={signature}"

    def validate_presigned_get(self, key: str, expires: int, signature: str) -> Path:
        if expires < int(time.time()):
            raise ValueError("expired storage signature")
        canonical_key = parse_object_key(key).key
        expected = self._signature(canonical_key, expires)
        if not hmac.compare_digest(expected, signature):
            raise ValueError("invalid storage signature")
        target = self.resolve_key(canonical_key)
        if not target.is_file():
            raise FileNotFoundError(canonical_key)
        return target
