from dataclasses import dataclass
import re
from uuid import uuid4


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*\.[a-z0-9]+$")
_PERMANENT_CATEGORIES = {"photos", "signatures"}
_AUDIO_CATEGORIES = {"audio-pending", "audio-expiring"}


@dataclass(frozen=True)
class ParsedObjectKey:
    key: str
    environment: str
    owner_user_id: str
    order_id: str
    category: str
    filename: str


def _safe_segment(value: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or not _SAFE_SEGMENT.fullmatch(value)
    ):
        raise ValueError("invalid storage key segment")
    return value


def parse_object_key(key: str) -> ParsedObjectKey:
    if not isinstance(key, str):
        raise ValueError("invalid storage key")
    parts = key.split("/")
    if len(parts) != 7:
        raise ValueError("invalid storage key structure")
    for part in parts:
        _safe_segment(part)

    environment = parts[0]
    if parts[1] == "users" and parts[3] == "orders":
        owner_user_id = parts[2]
        order_id = parts[4]
        category = parts[5]
        filename = parts[6]
        if category not in _PERMANENT_CATEGORIES:
            raise ValueError("invalid storage key category")
    elif parts[1] in _AUDIO_CATEGORIES and parts[2] == "users" and parts[4] == "orders":
        category = parts[1]
        owner_user_id = parts[3]
        order_id = parts[5]
        filename = parts[6]
    else:
        raise ValueError("invalid storage key structure")

    if not _SAFE_FILENAME.fullmatch(filename):
        raise ValueError("invalid storage key filename")
    canonical_key = "/".join(parts)
    return ParsedObjectKey(
        key=canonical_key,
        environment=environment,
        owner_user_id=owner_user_id,
        order_id=order_id,
        category=category,
        filename=filename,
    )


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
    if category not in _PERMANENT_CATEGORIES | _AUDIO_CATEGORIES:
        raise ValueError("unsupported object category")
    if not re.fullmatch(r"\.[a-z0-9]+", suffix):
        raise ValueError("unsupported object suffix")
    filename = f"{uuid4().hex}{suffix}"
    if category in _AUDIO_CATEGORIES:
        key = f"{environment}/{category}/users/{user_id}/orders/{order_id}/{filename}"
    else:
        key = f"{environment}/users/{user_id}/orders/{order_id}/{category}/{filename}"
    return parse_object_key(key).key
