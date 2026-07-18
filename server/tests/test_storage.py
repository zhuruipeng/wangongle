from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import importlib
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from sqlalchemy import update
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from server.models import ServiceOrder, ServiceOrderPhoto, User
from server.services.report_generator import GeneratedReportResult
from server.settings import AiReportSettings, StorageSettings, get_storage_settings
from server.storage import CosStorage, LocalStorage, build_object_key


class FakeCosClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def put_object(self, **kwargs: Any) -> None:
        kwargs["Body"] = kwargs["Body"].read()
        self.calls.append(("put", kwargs))

    def download_file(self, **kwargs: Any) -> None:
        self.calls.append(("download", kwargs))

    def copy_object(self, **kwargs: Any) -> None:
        self.calls.append(("copy", kwargs))

    def delete_object(self, **kwargs: Any) -> None:
        self.calls.append(("delete", kwargs))

    def get_presigned_url(self, **kwargs: Any) -> str:
        self.calls.append(("presign", kwargs))
        return "https://private.example/signed"


@pytest.fixture
def local_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalStorage:
    storage = LocalStorage(tmp_path / "objects", signing_secret="test-storage-signing-secret")
    monkeypatch.setattr("server.routers.orders.get_storage", lambda: storage)
    return storage


def test_local_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    key = "development/users/u1/orders/o1/photos/a.jpg"
    storage.put(key, BytesIO(b"image"), "image/jpeg")
    copied_key = "development/users/u1/orders/o1/signatures/copied.jpg"
    storage.copy(key, copied_key)
    assert storage.exists(key)
    assert storage.exists(copied_key)
    target = tmp_path / "download.jpg"
    storage.download_to(key, target)
    assert target.read_bytes() == b"image"
    moved_key = "development/users/u1/orders/o1/signatures/a.jpg"
    storage.move(key, moved_key)
    assert storage.exists(moved_key)
    storage.delete(moved_key)
    assert not storage.exists(moved_key)


@pytest.mark.parametrize("key", ["../secret", "development/../../secret", "/absolute"])
def test_local_storage_rejects_paths_outside_root(tmp_path: Path, key: str) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValueError, match="storage key"):
        storage.put(key, BytesIO(b"secret"), "application/octet-stream")


def test_object_key_contains_only_ids() -> None:
    key = build_object_key("production", "user-id", "order-id", "photos", ".jpg")
    assert key.startswith("production/users/user-id/orders/order-id/photos/")
    assert key.endswith(".jpg")
    pending = build_object_key("production", "user-id", "order-id", "audio-pending", ".mp3")
    assert pending.startswith("production/audio-pending/users/user-id/orders/order-id/")


def test_signed_dotdot_key_cannot_cross_local_storage_owner(
    local_storage: LocalStorage,
) -> None:
    from fastapi import HTTPException
    from server.routers.orders import get_private_local_file

    victim_key = build_object_key(
        "development", "victim", "victim-order", "photos", ".jpg"
    )
    local_storage.put(victim_key, BytesIO(b"victim-private-data"), "image/jpeg")
    filename = victim_key.rsplit("/", 1)[1]
    malicious_key = (
        "development/users/attacker/orders/attacker-order/photos/"
        f"../../../../victim/orders/victim-order/photos/{filename}"
    )
    expires = int(time.time()) + 300
    signature = hmac.new(
        b"test-storage-signing-secret",
        f"{malicious_key}:{expires}".encode("utf-8"),
        sha256,
    ).hexdigest()

    with pytest.raises(HTTPException) as rejected:
        get_private_local_file(
            malicious_key,
            expires=expires,
            signature=signature,
            current_user=User(id="attacker", openid="attacker-openid"),
        )

    assert rejected.value.status_code in {403, 404}
    assert local_storage.resolve_key(victim_key).read_bytes() == b"victim-private-data"


@pytest.mark.parametrize(
    "key",
    [
        "development/users/u1/orders/o1/photos/../a.jpg",
        "development/users/u1/orders/o1/./photos/a.jpg",
        "development/users//orders/o1/photos/a.jpg",
        r"development/users/u1/orders/o1/photos\\..\\a.jpg",
        unquote("development/users/u1/orders/o1/photos/%2e%2e/a.jpg"),
        unquote("development/users/u1%2F%2Forders/o1/photos/a.jpg"),
    ],
)
def test_object_key_parser_rejects_ambiguous_segments(tmp_path: Path, key: str) -> None:
    from server.storage import parse_object_key

    storage = LocalStorage(tmp_path, signing_secret="test-storage-signing-secret")
    with pytest.raises(ValueError, match="storage key"):
        parse_object_key(key)
    with pytest.raises(ValueError, match="storage key"):
        storage.presigned_get_url(key, expires_seconds=300)


def test_local_signing_fallback_is_random_but_stable_within_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    first = LocalStorage(tmp_path)
    second = LocalStorage(tmp_path)

    challenge = b"ganwanle-local-storage-test-challenge-v1"
    parent_proof = hmac.new(first._signing_secret, challenge, sha256).hexdigest()
    second_proof = hmac.new(second._signing_secret, challenge, sha256).hexdigest()
    assert hmac.compare_digest(parent_proof, second_proof)

    child_script = (
        "from hashlib import sha256; import hmac; "
        "from pathlib import Path; from tempfile import TemporaryDirectory; "
        "from server.storage.local import LocalStorage; "
        "root = TemporaryDirectory(); "
        "storage = LocalStorage(Path(root.name)); "
        "challenge = b'ganwanle-local-storage-test-challenge-v1'; "
        "print(hmac.new(storage._signing_secret, challenge, sha256).hexdigest())"
    )
    child_proofs = {
        subprocess.check_output([sys.executable, "-c", child_script], text=True).strip()
        for _ in range(2)
    }
    assert len(child_proofs) == 2
    assert parent_proof not in child_proofs

    key = build_object_key("development", "u1", "o1", "photos", ".jpg")
    first.put(key, BytesIO(b"private"), "image/jpeg")
    signed_url = urlparse(first.presigned_get_url(key, expires_seconds=300))
    query = parse_qs(signed_url.query)
    assert second.validate_presigned_get(
        key,
        expires=int(query["expires"][0]),
        signature=query["signature"][0],
    ).read_bytes() == b"private"


def test_local_signing_fallback_survives_storage_cache_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.storage import get_storage

    monkeypatch.setenv("GANWANLE_ENV", "development")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.delenv("JWT_SECRET", raising=False)
    get_storage.cache_clear()
    try:
        first = get_storage()
        assert isinstance(first, LocalStorage)
        key = build_object_key("development", "u1", "o1", "photos", ".jpg")
        first.put(key, BytesIO(b"cache-reset-private"), "image/jpeg")
        signed_url = urlparse(first.presigned_get_url(key, expires_seconds=300))
        query = parse_qs(signed_url.query)

        get_storage.cache_clear()
        second = get_storage()
        assert isinstance(second, LocalStorage)
        assert second.validate_presigned_get(
            key,
            expires=int(query["expires"][0]),
            signature=query["signature"][0],
        ).read_bytes() == b"cache-reset-private"
    finally:
        get_storage.cache_clear()


@pytest.mark.parametrize(
    "module_name",
    [
        "server.test_smoke",
        "server.test_report_generation",
        "server.test_transcription",
    ],
)
def test_legacy_run_closes_test_client(
    module_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(module_name)
    test_client = module.build_test_client()
    original_close = test_client.close
    close_count = 0

    def tracked_close() -> None:
        nonlocal close_count
        close_count += 1
        original_close()

    monkeypatch.setattr(test_client, "close", tracked_close)
    monkeypatch.setattr(module, "build_test_client", lambda: test_client)
    try:
        module.run()
        assert close_count == 1
    finally:
        if close_count == 0:
            original_close()


def test_cos_storage_uses_private_put_copy_delete_and_presigned_get(tmp_path: Path) -> None:
    client = FakeCosClient()
    settings = StorageSettings(
        environment="production",
        backend="cos",
        local_root=str(tmp_path),
        cos_secret_id="id",
        cos_secret_key="key",
        cos_region="ap-shanghai",
        cos_bucket="private-123",
        presigned_seconds=300,
    )
    storage = CosStorage(settings, client=client)
    storage.put("production/a.jpg", BytesIO(b"image"), "image/jpeg")
    storage.download_to("production/a.jpg", tmp_path / "download.jpg")
    storage.copy("production/a.jpg", "production/copied.jpg")
    storage.move("production/a.jpg", "production/b.jpg")
    assert storage.presigned_get_url("production/b.jpg", 120) == "https://private.example/signed"

    assert client.calls == [
        ("put", {
            "Bucket": "private-123", "Key": "production/a.jpg", "Body": b"image",
            "ContentType": "image/jpeg", "ACL": "private",
        }),
        ("download", {
            "Bucket": "private-123", "Key": "production/a.jpg",
            "DestFilePath": str(tmp_path / "download.jpg"),
        }),
        ("copy", {
            "Bucket": "private-123", "Key": "production/copied.jpg",
            "CopySource": {"Bucket": "private-123", "Key": "production/a.jpg", "Region": "ap-shanghai"},
            "ACL": "private",
        }),
        ("copy", {
            "Bucket": "private-123", "Key": "production/b.jpg",
            "CopySource": {"Bucket": "private-123", "Key": "production/a.jpg", "Region": "ap-shanghai"},
            "ACL": "private",
        }),
        ("delete", {"Bucket": "private-123", "Key": "production/a.jpg"}),
        ("presign", {
            "Bucket": "private-123", "Key": "production/b.jpg", "Method": "GET", "Expired": 120,
        }),
    ]


def test_cos_move_does_not_delete_when_copy_fails(tmp_path: Path) -> None:
    class CopyFailureClient(FakeCosClient):
        def copy_object(self, **kwargs: Any) -> None:
            raise RuntimeError("copy failed")

    client = CopyFailureClient()
    storage = CosStorage(StorageSettings(
        "production", "cos", str(tmp_path), "id", "key", "ap-shanghai", "private-123", 300
    ), client=client)
    with pytest.raises(RuntimeError, match="copy failed"):
        storage.move("source", "target")
    assert not any(name == "delete" for name, _kwargs in client.calls)


def test_cos_copy_never_deletes_source(tmp_path: Path) -> None:
    client = FakeCosClient()
    storage = CosStorage(StorageSettings(
        "production", "cos", str(tmp_path), "id", "key", "ap-shanghai", "private-123", 300
    ), client=client)
    storage.copy("source", "target")
    assert [name for name, _kwargs in client.calls] == ["copy"]


def test_production_storage_settings_require_private_cos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GANWANLE_ENV", "production")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    with pytest.raises(RuntimeError, match="COS"):
        get_storage_settings()

    monkeypatch.setenv("STORAGE_BACKEND", "cos")
    with pytest.raises(RuntimeError, match="credentials"):
        get_storage_settings()

    monkeypatch.setenv("COS_SECRET_ID", "id")
    monkeypatch.setenv("COS_SECRET_KEY", "key")
    monkeypatch.setenv("COS_BUCKET", "private-123")
    monkeypatch.setenv("COS_PRESIGNED_SECONDS", "59")
    with pytest.raises(RuntimeError, match="60.*900"):
        get_storage_settings()


@pytest.mark.parametrize("local_root", ["", "   "])
def test_local_storage_settings_reject_empty_root(
    monkeypatch: pytest.MonkeyPatch,
    local_root: str,
) -> None:
    monkeypatch.setenv("GANWANLE_ENV", "development")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", local_root)
    with pytest.raises(RuntimeError, match="LOCAL_STORAGE_ROOT"):
        get_storage_settings()


def test_photo_is_private_signed_and_owner_scoped(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    local_storage: LocalStorage,
) -> None:
    owner = auth_headers("photo-owner")
    stranger = auth_headers("photo-stranger")
    order_id = create_order(owner)["id"]
    response = client.post(
        f"/api/v1/service-orders/{order_id}/photos",
        headers=owner,
        data={"phase": "before"},
        files={"file": ("before.jpg", b"private-image", "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    photo_json = response.json()
    assert photo_json["content_type"] == "image/jpeg"
    assert photo_json["size_bytes"] == len(b"private-image")
    assert photo_json["sha256"] == sha256(b"private-image").hexdigest()
    parsed = urlparse(photo_json["file_url"])
    assert parsed.path.startswith("/api/v1/service-orders/private-files/")
    assert parse_qs(parsed.query)["expires"]
    assert parse_qs(parsed.query)["signature"]

    photo = db_session.get(ServiceOrderPhoto, photo_json["id"])
    assert photo is not None
    assert photo.file_url == ""
    assert photo.object_key.startswith(f"test/users/")
    assert photo.object_key.endswith(".jpg")
    assert photo.content_type == "image/jpeg"
    assert photo.size_bytes == len(b"private-image")
    assert photo.sha256 == sha256(b"private-image").hexdigest()
    assert local_storage.exists(photo.object_key)

    assert client.get(photo_json["file_url"], headers=owner).content == b"private-image"
    assert client.get(photo_json["file_url"], headers=stranger).status_code == 404
    assert client.get(photo_json["file_url"]).status_code == 401
    tampered = photo_json["file_url"].replace("signature=", "signature=0", 1)
    assert client.get(tampered, headers=owner).status_code in {403, 422}
    assert client.get(parsed.path, headers=owner).status_code == 422
    assert client.get("/uploads/photos/anything.jpg").status_code == 404


def test_upload_validation_preserves_mime_extension_and_size_limits(
    client,
    auth_headers,
    create_order,
    local_storage: LocalStorage,
) -> None:
    owner = auth_headers("upload-validation")
    order_id = create_order(owner)["id"]
    wrong_mime = client.post(
        f"/api/v1/service-orders/{order_id}/photos", headers=owner, data={"phase": "before"},
        files={"file": ("before.jpg", b"image", "text/plain")},
    )
    wrong_extension = client.post(
        f"/api/v1/service-orders/{order_id}/photos", headers=owner, data={"phase": "before"},
        files={"file": ("before.exe", b"image", "image/jpeg")},
    )
    too_large = client.post(
        f"/api/v1/service-orders/{order_id}/photos", headers=owner, data={"phase": "before"},
        files={"file": ("before.jpg", b"x" * (10 * 1024 * 1024 + 1), "image/jpeg")},
    )
    assert wrong_mime.status_code == 415
    assert wrong_extension.status_code == 415
    assert too_large.status_code == 413
    assert list(local_storage.root.rglob("*.*")) == []


def test_photo_upload_cleans_object_when_audit_fails(
    client,
    auth_headers,
    create_order,
    local_storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = auth_headers("photo-audit-failure")
    order_id = create_order(owner)["id"]
    monkeypatch.setattr("server.routers.orders.add_audit", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")))
    response = client.post(
        f"/api/v1/service-orders/{order_id}/photos",
        headers=owner,
        data={"phase": "before"},
        files={"file": ("before.jpg", b"new-object", "image/jpeg")},
    )
    assert response.status_code == 500
    assert list(local_storage.root.rglob("*.jpg")) == []


def test_photo_upload_rollback_delete_failure_enqueues_cleanup(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    local_storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.models import StorageCleanupJob

    owner = auth_headers("photo-upload-cleanup-job")
    order_id = create_order(owner)["id"]
    monkeypatch.setattr(
        "server.routers.orders.add_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )
    monkeypatch.setattr(
        local_storage,
        "delete",
        lambda _key: (_ for _ in ()).throw(RuntimeError("provider secret must not leak")),
    )
    response = client.post(
        f"/api/v1/service-orders/{order_id}/photos", headers=owner, data={"phase": "before"},
        files={"file": ("before.jpg", b"new-object", "image/jpeg")},
    )
    assert response.status_code == 500
    assert "provider secret" not in response.text
    jobs = db_session.query(StorageCleanupJob).all()
    assert len(jobs) == 1
    assert jobs[0].source == "photo_upload_rollback"
    assert jobs[0].object_key.endswith(".jpg")
    assert jobs[0].attempt_count == 0
    assert jobs[0].last_error is None


def test_audio_replace_ambiguous_commit_keeps_old_row_and_both_pending_objects(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    local_storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = auth_headers("audio-rollback")
    order_id = create_order(owner)["id"]
    first = client.post(
        f"/api/v1/service-orders/{order_id}/audio", headers=owner,
        files={"file": ("first.mp3", b"first-audio", "audio/mpeg")},
    )
    assert first.status_code == 200, first.text
    old_key = db_session.get(ServiceOrder, order_id).audio_object_key
    assert old_key and local_storage.exists(old_key)

    original_commit = db_session.commit
    monkeypatch.setattr(db_session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
    second = client.post(
        f"/api/v1/service-orders/{order_id}/audio", headers=owner,
        files={"file": ("second.mp3", b"second-audio", "audio/mpeg")},
    )
    assert second.status_code == 503
    assert second.json() == {"detail": "录音处理状态保存失败，请稍后重试"}
    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.expire_all()
    assert db_session.get(ServiceOrder, order_id).audio_object_key == old_key
    assert local_storage.exists(old_key)
    ambiguous_objects = list(local_storage.root.rglob("*.mp3"))
    assert len(ambiguous_objects) == 2

    succeeded = client.post(
        f"/api/v1/service-orders/{order_id}/audio", headers=owner,
        files={"file": ("third.mp3", b"third-audio", "audio/mpeg")},
    )
    assert succeeded.status_code == 200, succeeded.text
    db_session.expire_all()
    new_key = db_session.get(ServiceOrder, order_id).audio_object_key
    assert new_key != old_key
    assert local_storage.exists(new_key)
    assert not local_storage.exists(old_key)
    assert len(list(local_storage.root.rglob("*.mp3"))) == 2


def test_successful_audio_replacement_delete_failure_enqueues_cleanup(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    local_storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.models import StorageCleanupJob

    owner = auth_headers("audio-replace-cleanup-job")
    order_id = create_order(owner)["id"]
    first = client.post(
        f"/api/v1/service-orders/{order_id}/audio", headers=owner,
        files={"file": ("first.mp3", b"first-audio", "audio/mpeg")},
    )
    assert first.status_code == 200, first.text
    old_key = db_session.get(ServiceOrder, order_id).audio_object_key
    original_delete = local_storage.delete

    def fail_old_delete(key: str) -> None:
        if key == old_key:
            raise RuntimeError("provider secret must not leak")
        original_delete(key)

    monkeypatch.setattr(local_storage, "delete", fail_old_delete)
    replaced = client.post(
        f"/api/v1/service-orders/{order_id}/audio", headers=owner,
        files={"file": ("second.mp3", b"second-audio", "audio/mpeg")},
    )
    assert replaced.status_code == 200
    assert "provider secret" not in replaced.text
    job = db_session.query(StorageCleanupJob).one()
    assert (job.object_key, job.source) == (old_key, "audio_replacement")


def test_photo_delete_commits_row_before_deleting_object(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    local_storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = auth_headers("photo-delete-rollback")
    order_id = create_order(owner)["id"]
    uploaded = client.post(
        f"/api/v1/service-orders/{order_id}/photos", headers=owner, data={"phase": "after"},
        files={"file": ("after.jpg", b"keep-on-db-failure", "image/jpeg")},
    ).json()
    photo = db_session.get(ServiceOrderPhoto, uploaded["id"])
    key = photo.object_key

    original_commit = db_session.commit
    monkeypatch.setattr(db_session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
    deleted = client.delete(
        f"/api/v1/service-orders/{order_id}/photos/{photo.id}", headers=owner
    )
    assert deleted.status_code == 500
    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.rollback()
    assert db_session.get(ServiceOrderPhoto, photo.id) is not None
    assert local_storage.exists(key)


def test_photo_delete_storage_failure_is_best_effort_after_db_commit(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    local_storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.models import StorageCleanupJob

    owner = auth_headers("photo-delete-storage-failure")
    order_id = create_order(owner)["id"]
    uploaded = client.post(
        f"/api/v1/service-orders/{order_id}/photos", headers=owner, data={"phase": "before"},
        files={"file": ("before.jpg", b"orphan-on-delete-failure", "image/jpeg")},
    ).json()
    photo = db_session.get(ServiceOrderPhoto, uploaded["id"])
    key = photo.object_key
    monkeypatch.setattr(local_storage, "delete", lambda _key: (_ for _ in ()).throw(RuntimeError("COS unavailable")))

    response = client.delete(
        f"/api/v1/service-orders/{order_id}/photos/{photo.id}", headers=owner
    )
    assert response.status_code == 204
    assert db_session.get(ServiceOrderPhoto, photo.id) is None
    assert local_storage.exists(key)
    job = db_session.query(StorageCleanupJob).one()
    assert (job.object_key, job.source) == (key, "photo_delete")


def test_cleanup_retry_removes_success_and_retains_safe_failed_job(db_session: Session) -> None:
    from server.models import StorageCleanupJob
    from server.storage.cleanup import retry_storage_cleanup

    successful = StorageCleanupJob(object_key="production/delete-me", source="photo_delete")
    failed = StorageCleanupJob(object_key="production/retry-me", source="audio_replacement")
    db_session.add_all([successful, failed])
    db_session.commit()

    class RetryStorage:
        def __init__(self) -> None:
            self.fail = True

        def delete(self, key: str) -> None:
            if key == "production/retry-me" and self.fail:
                raise RuntimeError("provider secret must not be persisted")

    storage = RetryStorage()
    assert retry_storage_cleanup(db_session, storage) == {"succeeded": 1, "failed": 1}
    remaining = db_session.query(StorageCleanupJob).one()
    assert remaining.id == failed.id
    assert remaining.attempt_count == 1
    assert remaining.last_error == "storage delete failed"
    assert "provider secret" not in remaining.last_error

    storage.fail = False
    assert retry_storage_cleanup(db_session, storage) == {"succeeded": 1, "failed": 0}
    assert db_session.query(StorageCleanupJob).count() == 0


def test_cleanup_retry_does_not_starve_new_jobs_behind_poison_batch(
    db_session: Session,
) -> None:
    from server.models import StorageCleanupJob
    from server.storage.cleanup import retry_storage_cleanup

    now = datetime.now(timezone.utc)
    jobs = [
        StorageCleanupJob(
            object_key=f"production/poison-{index}",
            source="photo_delete",
            created_at=now + timedelta(seconds=index),
            updated_at=now + timedelta(seconds=index),
        )
        for index in range(3)
    ]
    db_session.add_all(jobs)
    db_session.commit()

    class PoisonStorage:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def delete(self, key: str) -> None:
            self.calls.append(key)
            raise RuntimeError("still unavailable")

    storage = PoisonStorage()
    assert retry_storage_cleanup(db_session, storage, limit=2) == {"succeeded": 0, "failed": 2}
    assert storage.calls == ["production/poison-0", "production/poison-1"]

    storage.calls.clear()
    assert retry_storage_cleanup(db_session, storage, limit=2) == {"succeeded": 0, "failed": 2}
    assert "production/poison-2" in storage.calls

    attempts_before = {job.object_key: job.attempt_count for job in db_session.query(StorageCleanupJob)}
    storage.calls.clear()
    assert retry_storage_cleanup(db_session, storage, limit=2) == {"succeeded": 0, "failed": 2}
    attempts_after = {job.object_key: job.attempt_count for job in db_session.query(StorageCleanupJob)}
    assert storage.calls
    assert sum(attempts_after.values()) == sum(attempts_before.values()) + 2


def test_cleanup_batch_uses_postgres_skip_locked_and_sqlite_compatible_sql() -> None:
    from sqlalchemy.dialects import postgresql, sqlite

    from server.storage.cleanup import storage_cleanup_batch_statement

    statement = storage_cleanup_batch_statement(limit=10)
    postgres_sql = str(statement.compile(dialect=postgresql.dialect()))
    sqlite_sql = str(statement.compile(dialect=sqlite.dialect()))
    assert "ORDER BY storage_cleanup_jobs.attempt_count" in postgres_sql
    assert "FOR UPDATE SKIP LOCKED" in postgres_sql
    assert "FOR UPDATE" not in sqlite_sql


def _configured_report() -> AiReportSettings:
    return AiReportSettings(True, "key", "https://example.invalid", "test-model")


def _generated_report() -> GeneratedReportResult:
    from server.schemas import GeneratedCompletedItem, GeneratedServiceReport

    return GeneratedReportResult(
        report=GeneratedServiceReport(
            summary="完成安装",
            completed_items=[GeneratedCompletedItem(content="完成安装", source_text="完成安装")],
            materials=[], labor_items=[], risks=[], after_sales=[], missing_information=[], warnings=[],
        ),
        total_amount_cents=0,
    )


def test_stale_report_processing_lease_can_be_reclaimed(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = auth_headers("stale-report")
    order_id = create_order(owner, transcript="完成安装")["id"]
    order = db_session.get(ServiceOrder, order_id)
    order.transcript = "完成安装"
    order.report_generation_status = "processing"
    order.updated_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db_session.commit()
    monkeypatch.setattr("server.routers.orders.get_ai_report_settings", _configured_report)
    monkeypatch.setattr("server.routers.orders.generate_service_report", lambda *args: _generated_report())

    response = client.post(f"/api/v1/service-orders/{order_id}/generate-report", headers=owner)
    assert response.status_code == 200, response.text
    assert client.get(f"/api/v1/service-orders/{order_id}", headers=owner).json()["report_generation_status"] == "succeeded"


def test_unexpected_report_error_transitions_claim_to_failed(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = auth_headers("unexpected-report")
    order_id = create_order(owner, transcript="完成安装")["id"]
    db_session.get(ServiceOrder, order_id).transcript = "完成安装"
    db_session.commit()
    monkeypatch.setattr("server.routers.orders.get_ai_report_settings", _configured_report)
    monkeypatch.setattr("server.routers.orders.generate_service_report", lambda *args: (_ for _ in ()).throw(RuntimeError("provider exploded")))

    assert client.post(f"/api/v1/service-orders/{order_id}/generate-report", headers=owner).status_code == 500
    detail = client.get(f"/api/v1/service-orders/{order_id}", headers=owner).json()
    assert detail["report_generation_status"] == "failed"
    assert detail["report_generation_error"] == "服务报告生成失败"


def test_fresh_report_processing_lease_rejects_duplicate_claim(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = auth_headers("fresh-report")
    order_id = create_order(owner)["id"]
    order = db_session.get(ServiceOrder, order_id)
    order.transcript = "完成安装"
    order.report_generation_status = "processing"
    order.updated_at = datetime.now(timezone.utc)
    db_session.commit()
    monkeypatch.setattr("server.routers.orders.get_ai_report_settings", _configured_report)
    provider_called = False

    def provider(*args: Any) -> GeneratedReportResult:
        nonlocal provider_called
        provider_called = True
        return _generated_report()

    monkeypatch.setattr("server.routers.orders.generate_service_report", provider)
    response = client.post(f"/api/v1/service-orders/{order_id}/generate-report", headers=owner)
    assert response.status_code == 409
    assert provider_called is False


def test_non_force_report_claim_is_atomic_with_existing_report(tmp_path: Path) -> None:
    from server.database import Base
    from server.models import User
    from server.routers.orders import build_report_claim_statement

    engine = create_engine(f"sqlite:///{tmp_path / 'claim.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as setup:
        user = User(openid="claim-user", technician_name="师傅")
        setup.add(user)
        setup.flush()
        order = ServiceOrder(
            owner_user_id=user.id,
            order_no="CLAIM-1",
            company_name="公司",
            customer_name="客户",
            customer_phone="13800000000",
            service_address="地址",
            service_type="空调安装",
            technician_name="师傅",
            transcript="完成安装",
        )
        setup.add(order)
        setup.commit()
        user_id, order_id = user.id, order.id

    claim_time = datetime.now(timezone.utc)
    non_force_statement = build_report_claim_statement(
        order_id, user_id, "model", claim_time, force=False
    )
    force_statement = build_report_claim_statement(
        order_id, user_id, "model", claim_time, force=True
    )
    compiled_non_force = str(non_force_statement.compile(engine))
    compiled_force = str(force_statement.compile(engine))
    assert "report_json IS NULL" in compiled_non_force
    assert "report_json IS NULL" not in compiled_force

    with sessions() as stale_session, sessions() as winning_session:
        stale_session.get(ServiceOrder, order_id)
        winner = winning_session.get(ServiceOrder, order_id)
        winner.report_json = '{"winner":true}'
        winning_session.commit()
        claimed = stale_session.execute(non_force_statement)
        stale_session.commit()
        assert claimed.rowcount == 0
        stale_session.expire_all()
        persisted = stale_session.get(ServiceOrder, order_id)
        assert persisted.report_json == '{"winner":true}'
        assert persisted.report_generation_status == "not_started"

        forced = stale_session.execute(force_statement)
        stale_session.commit()
        assert forced.rowcount == 1
        stale_session.expire_all()
        assert stale_session.get(ServiceOrder, order_id).report_generation_status == "processing"

    engine.dispose()


def test_stale_report_worker_cannot_overwrite_reclaimed_claim(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = auth_headers("report-fencing")
    order_id = create_order(owner)["id"]
    order = db_session.get(ServiceOrder, order_id)
    order.transcript = "完成安装"
    db_session.commit()
    monkeypatch.setattr("server.routers.orders.get_ai_report_settings", _configured_report)
    newer_claim_time = datetime.now(timezone.utc) + timedelta(seconds=1)

    def reclaim_while_old_worker_runs(*args: Any) -> GeneratedReportResult:
        db_session.execute(
            update(ServiceOrder)
            .where(ServiceOrder.id == order_id)
            .values(report_generation_status="processing", updated_at=newer_claim_time)
        )
        db_session.commit()
        return _generated_report()

    monkeypatch.setattr("server.routers.orders.generate_service_report", reclaim_while_old_worker_runs)
    response = client.post(f"/api/v1/service-orders/{order_id}/generate-report", headers=owner)
    assert response.status_code == 409
    db_session.expire_all()
    persisted = db_session.get(ServiceOrder, order_id)
    assert persisted.report_generation_status == "processing"
    assert persisted.report_json is None
    persisted_time = persisted.updated_at
    if persisted_time.tzinfo is None:
        persisted_time = persisted_time.replace(tzinfo=timezone.utc)
    assert persisted_time == newer_claim_time


def test_report_result_commit_failure_recovers_processing_claim(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = auth_headers("report-commit-failure")
    order_id = create_order(owner, transcript="完成安装")["id"]
    db_session.get(ServiceOrder, order_id).transcript = "完成安装"
    db_session.commit()
    monkeypatch.setattr("server.routers.orders.get_ai_report_settings", _configured_report)
    monkeypatch.setattr("server.routers.orders.generate_service_report", lambda *args: _generated_report())
    original_commit = db_session.commit
    commit_count = 0

    def fail_result_commit_once() -> None:
        nonlocal commit_count
        commit_count += 1
        if commit_count == 2:
            raise RuntimeError("result commit failed")
        original_commit()

    monkeypatch.setattr(db_session, "commit", fail_result_commit_once)
    assert client.post(f"/api/v1/service-orders/{order_id}/generate-report", headers=owner).status_code == 500
    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.expire_all()
    order = db_session.get(ServiceOrder, order_id)
    assert order.report_generation_status == "failed"
    assert order.report_generation_error == "服务报告生成失败"
