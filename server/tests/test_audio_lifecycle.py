from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from server.models import AuditEvent, ServiceOrder, StorageCleanupJob
from server.services.speech_to_text import SpeechToTextError
from server.services.tencent_asr import TencentAsrResult
from server.settings import AsrSettings
from server.storage import LocalStorage, build_object_key
from server.storage.cleanup import retry_storage_cleanup


CONFIGURED_ASR = AsrSettings(True, "id", "key", "ap-shanghai", "16k_zh", "")
SAFE_DUPLICATE = {"detail": "录音正在处理或已完成转写"}


class TrackingStorage(LocalStorage):
    def __init__(self, root: Path) -> None:
        super().__init__(root, signing_secret="audio-lifecycle-test-secret")
        self.copies: list[tuple[str, str]] = []
        self.moves: list[tuple[str, str]] = []
        self.partial_copy_failure = False
        self.fail_pending_delete = False

    def copy(self, source_key: str, target_key: str) -> None:
        self.copies.append((source_key, target_key))
        super().copy(source_key, target_key)
        if self.partial_copy_failure:
            raise RuntimeError("copy provider credential must not leak")

    def move(self, source_key: str, target_key: str) -> None:
        self.moves.append((source_key, target_key))
        super().move(source_key, target_key)

    def delete(self, key: str) -> None:
        if self.fail_pending_delete and "/audio-pending/" in f"/{key}":
            raise RuntimeError("delete provider credential must not leak")
        super().delete(key)


@pytest.fixture
def lifecycle_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TrackingStorage:
    storage = TrackingStorage(tmp_path / "audio-lifecycle")
    monkeypatch.setattr("server.routers.orders.get_storage", lambda: storage)
    monkeypatch.setattr("server.routers.orders.get_asr_settings", lambda: CONFIGURED_ASR)
    return storage


@pytest.fixture
def owner_order(client, auth_headers, create_order):
    sequence = 0

    def create(*, audio: bool = False, status: str = "in_progress"):
        nonlocal sequence
        sequence += 1
        headers = auth_headers(f"audio-lifecycle-owner-{sequence}")
        order_id = create_order(headers, status=status)["id"]
        if audio:
            response = client.post(
                f"/api/v1/service-orders/{order_id}/audio",
                headers=headers,
                files={"file": ("voice.mp3", b"ID3-lifecycle-audio", "audio/mpeg")},
            )
            assert response.status_code == 200, response.text
        return order_id, headers

    return create


def successful_asr(_path: Path, _settings: AsrSettings) -> TencentAsrResult:
    return TencentAsrResult("完成空调安装", "asr-request", 1200)


def test_transcription_copies_then_commits_cleanup_job_and_expiry(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    source_key = db_session.get(ServiceOrder, order_id).audio_object_key
    lifecycle_storage.fail_pending_delete = True
    before = datetime.now(timezone.utc)
    observed_claims: list[str] = []

    def assert_claim(path: Path, settings: AsrSettings) -> TencentAsrResult:
        del path, settings
        db_session.expire_all()
        processing = db_session.get(ServiceOrder, order_id)
        assert processing.transcription_status == "processing"
        assert processing.transcription_claim_token
        observed_claims.append(processing.transcription_claim_token)
        return successful_asr(Path("unused"), CONFIGURED_ASR)

    monkeypatch.setattr("server.routers.orders.transcribe_audio", assert_claim)
    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"
    assert observed_claims
    assert lifecycle_storage.moves == []
    copied_source, target = lifecycle_storage.copies[0]
    assert copied_source == source_key
    assert "/audio-pending/" in f"/{copied_source}"
    assert "/audio-expiring/" in f"/{target}"
    assert lifecycle_storage.exists(source_key)
    assert lifecycle_storage.exists(target)
    db_session.expire_all()
    order = db_session.get(ServiceOrder, order_id)
    assert order.audio_object_key == target
    assert order.transcription_status == "succeeded"
    assert order.transcription_claim_token is None
    assert order.audio_delete_after.tzinfo is not None
    assert before + timedelta(days=7) <= order.audio_delete_after <= datetime.now(timezone.utc) + timedelta(days=7)
    job = db_session.scalar(select(StorageCleanupJob).where(StorageCleanupJob.object_key == source_key))
    assert job is not None
    assert job.source == "audio_transition_source"

    lifecycle_storage.fail_pending_delete = False
    assert retry_storage_cleanup(db_session, lifecycle_storage) == {"succeeded": 1, "failed": 0}
    assert not lifecycle_storage.exists(source_key)
    assert lifecycle_storage.exists(target)


def test_transcription_temporary_download_is_deleted(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del lifecycle_storage
    order_id, headers = owner_order(audio=True)
    downloaded_path: list[Path] = []

    def inspect_path(path: Path, settings: AsrSettings) -> TencentAsrResult:
        del settings
        assert path.exists()
        downloaded_path.append(path)
        return TencentAsrResult("完成", "request", 100)

    monkeypatch.setattr("server.routers.orders.transcribe_audio", inspect_path)
    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert response.status_code == 200, response.text
    assert downloaded_path and not downloaded_path[0].exists()
    assert not downloaded_path[0].parent.exists()


def test_failed_recognition_leaves_pending_audio_retryable(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    pending_key = db_session.get(ServiceOrder, order_id).audio_object_key
    monkeypatch.setattr(
        "server.routers.orders.transcribe_audio",
        lambda path, settings: (_ for _ in ()).throw(SpeechToTextError("识别失败")),
    )
    failed = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert lifecycle_storage.copies == []
    assert lifecycle_storage.moves == []
    assert lifecycle_storage.exists(pending_key)
    db_session.expire_all()
    assert db_session.get(ServiceOrder, order_id).audio_object_key == pending_key

    monkeypatch.setattr("server.routers.orders.transcribe_audio", successful_asr)
    retried = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["status"] == "succeeded"


@pytest.mark.parametrize("state", ["processing", "succeeded"])
def test_duplicate_transcription_state_returns_fixed_conflict_without_asr(
    client,
    owner_order,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    order_id, headers = owner_order(audio=True)
    order = db_session.get(ServiceOrder, order_id)
    order.transcription_status = state
    db_session.commit()
    monkeypatch.setattr(
        "server.routers.orders.transcribe_audio",
        lambda path, settings: (_ for _ in ()).throw(AssertionError("ASR must not run")),
    )
    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert response.status_code == 409, response.text
    assert response.json() == SAFE_DUPLICATE


def test_expiring_audio_key_is_never_retranscribed(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order()
    order = db_session.get(ServiceOrder, order_id)
    expiring_key = build_object_key("test", order.owner_user_id, order_id, "audio-expiring", ".mp3")
    lifecycle_storage.put(expiring_key, __import__("io").BytesIO(b"audio"), "audio/mpeg")
    order.audio_object_key = expiring_key
    order.transcription_status = "failed"
    db_session.commit()
    monkeypatch.setattr(
        "server.routers.orders.transcribe_audio",
        lambda path, settings: (_ for _ in ()).throw(AssertionError("ASR must not run")),
    )
    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert response.status_code == 409
    assert response.json() == SAFE_DUPLICATE


def test_partial_copy_exception_keeps_pending_source_and_compensates_target(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    source_key = db_session.get(ServiceOrder, order_id).audio_object_key
    lifecycle_storage.partial_copy_failure = True
    monkeypatch.setattr("server.routers.orders.transcribe_audio", successful_asr)
    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert response.status_code == 503
    assert "credential" not in response.text
    db_session.expire_all()
    order = db_session.get(ServiceOrder, order_id)
    assert order.audio_object_key == source_key
    assert order.audio_delete_after is None
    assert order.transcription_status == "failed"
    assert lifecycle_storage.exists(source_key)
    target_key = lifecycle_storage.copies[0][1]
    assert not lifecycle_storage.exists(target_key)
    assert lifecycle_storage.moves == []
    audit = db_session.scalar(select(AuditEvent).where(
        AuditEvent.resource_id == order_id,
        AuditEvent.event_type == "storage.audio_transition",
        AuditEvent.outcome == "failed",
    ))
    assert audit is not None


def test_claim_fencing_rejects_stale_worker_result_and_keeps_source(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    source_key = db_session.get(ServiceOrder, order_id).audio_object_key

    def supersede_claim(path: Path, settings: AsrSettings) -> TencentAsrResult:
        del path, settings
        db_session.expire_all()
        order = db_session.get(ServiceOrder, order_id)
        order.transcription_claim_token = "newer-worker-claim"
        order.updated_at = datetime.now(timezone.utc)
        db_session.commit()
        return successful_asr(Path("unused"), CONFIGURED_ASR)

    monkeypatch.setattr("server.routers.orders.transcribe_audio", supersede_claim)
    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert response.status_code == 409
    assert response.json() == SAFE_DUPLICATE
    db_session.expire_all()
    order = db_session.get(ServiceOrder, order_id)
    assert order.audio_object_key == source_key
    assert order.transcription_status == "processing"
    assert order.transcription_claim_token == "newer-worker-claim"
    assert lifecycle_storage.exists(source_key)
    assert not lifecycle_storage.exists(lifecycle_storage.copies[0][1])
    assert lifecycle_storage.moves == []


def test_continuous_terminal_db_failure_keeps_source_and_stale_claim_can_recover(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    source_key = db_session.get(ServiceOrder, order_id).audio_object_key
    monkeypatch.setattr("server.routers.orders.transcribe_audio", successful_asr)
    original_commit = db_session.commit
    commit_count = 0

    def fail_terminal_and_recovery_commits() -> None:
        nonlocal commit_count
        commit_count += 1
        if commit_count in {2, 3}:
            raise RuntimeError("database credential must not leak")
        original_commit()

    monkeypatch.setattr(db_session, "commit", fail_terminal_and_recovery_commits)
    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert response.status_code == 503
    assert response.json() == {"detail": "录音处理状态保存失败，请稍后重试"}
    assert "credential" not in response.text
    assert lifecycle_storage.exists(source_key)
    assert lifecycle_storage.moves == []
    if lifecycle_storage.copies:
        assert lifecycle_storage.exists(lifecycle_storage.copies[0][1])

    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.rollback()
    db_session.expire_all()
    stranded = db_session.get(ServiceOrder, order_id)
    assert stranded.audio_object_key == source_key
    assert stranded.transcription_status == "processing"
    assert stranded.transcription_claim_token
    stranded.updated_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    original_commit()

    recovered = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["status"] == "succeeded"


@pytest.mark.parametrize(
    ("transcription_status", "claim_token"),
    [("processing", "abandoned-claim"), ("failed", "unexpected-claim")],
)
def test_replacement_audio_rejects_any_processing_or_claim_including_stale(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    transcription_status: str,
    claim_token: str,
) -> None:
    order_id, headers = owner_order(audio=True)
    order = db_session.get(ServiceOrder, order_id)
    source_key = order.audio_object_key
    order.transcription_status = transcription_status
    order.transcription_claim_token = claim_token
    order.updated_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()

    response = client.post(
        f"/api/v1/service-orders/{order_id}/audio",
        headers=headers,
        files={"file": ("replacement.mp3", b"ID3-replacement", "audio/mpeg")},
    )
    assert response.status_code == 409
    db_session.expire_all()
    replaced = db_session.get(ServiceOrder, order_id)
    assert replaced.audio_object_key == source_key
    assert replaced.transcription_status == transcription_status
    assert replaced.transcription_claim_token == claim_token
    assert lifecycle_storage.exists(source_key)


def test_audio_upload_loses_race_to_terminal_transition_without_overwrite_or_orphan(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    current = db_session.get(ServiceOrder, order_id)
    source_key = current.audio_object_key
    target_key = build_object_key(
        "test", current.owner_user_id, order_id, "audio-expiring", ".mp3"
    )
    delete_after = datetime.now(timezone.utc) + timedelta(days=7)
    lifecycle_storage.put(target_key, __import__("io").BytesIO(b"canonical"), "audio/mpeg")
    original_put = lifecycle_storage.put
    replacement_keys: list[str] = []

    def terminal_wins_after_replacement_put(key, stream, content_type) -> None:
        original_put(key, stream, content_type)
        replacement_keys.append(key)
        with Session(db_session.get_bind()) as competitor:
            result = competitor.execute(
                update(ServiceOrder)
                .where(
                    ServiceOrder.id == order_id,
                    ServiceOrder.audio_object_key == source_key,
                )
                .values(
                    audio_object_key=target_key,
                    audio_delete_after=delete_after,
                    transcription_status="succeeded",
                    transcription_claim_token=None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            assert result.rowcount == 1
            competitor.commit()

    monkeypatch.setattr(lifecycle_storage, "put", terminal_wins_after_replacement_put)
    response = client.post(
        f"/api/v1/service-orders/{order_id}/audio",
        headers=headers,
        files={"file": ("replacement.mp3", b"ID3-replacement", "audio/mpeg")},
    )

    assert response.status_code == 409, response.text
    db_session.expire_all()
    persisted = db_session.get(ServiceOrder, order_id)
    assert persisted.audio_object_key == target_key
    assert persisted.transcription_status == "succeeded"
    assert persisted.audio_delete_after == delete_after
    assert lifecycle_storage.exists(target_key)
    assert replacement_keys and not lifecycle_storage.exists(replacement_keys[0])


def test_audio_upload_loses_race_to_transcription_claim_and_compensates_replacement(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    current = db_session.get(ServiceOrder, order_id)
    source_key = current.audio_object_key
    original_put = lifecycle_storage.put
    replacement_keys: list[str] = []

    def claim_wins_after_replacement_put(key, stream, content_type) -> None:
        original_put(key, stream, content_type)
        replacement_keys.append(key)
        with Session(db_session.get_bind()) as competitor:
            result = competitor.execute(
                update(ServiceOrder)
                .where(
                    ServiceOrder.id == order_id,
                    ServiceOrder.audio_object_key == source_key,
                )
                .values(
                    transcription_status="processing",
                    transcription_claim_token="winning-worker",
                    updated_at=datetime.now(timezone.utc),
                )
            )
            assert result.rowcount == 1
            competitor.commit()

    monkeypatch.setattr(lifecycle_storage, "put", claim_wins_after_replacement_put)
    response = client.post(
        f"/api/v1/service-orders/{order_id}/audio",
        headers=headers,
        files={"file": ("replacement.mp3", b"ID3-replacement", "audio/mpeg")},
    )

    assert response.status_code == 409, response.text
    db_session.expire_all()
    persisted = db_session.get(ServiceOrder, order_id)
    assert persisted.audio_object_key == source_key
    assert persisted.transcription_status == "processing"
    assert persisted.transcription_claim_token == "winning-worker"
    assert lifecycle_storage.exists(source_key)
    assert replacement_keys and not lifecycle_storage.exists(replacement_keys[0])


def test_audio_replacement_presign_failure_compensates_before_db_commit(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    source_key = db_session.get(ServiceOrder, order_id).audio_object_key
    monkeypatch.setattr(
        lifecycle_storage,
        "presigned_get_url",
        lambda key, expires: (_ for _ in ()).throw(RuntimeError("signing secret")),
    )

    response = client.post(
        f"/api/v1/service-orders/{order_id}/audio",
        headers=headers,
        files={"file": ("replacement.mp3", b"ID3-replacement", "audio/mpeg")},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "录音授权失败，请稍后重试"}
    assert "secret" not in response.text
    db_session.expire_all()
    persisted = db_session.get(ServiceOrder, order_id)
    assert persisted.audio_object_key == source_key
    assert lifecycle_storage.exists(source_key)
    assert len(list(lifecycle_storage.root.rglob("*.mp3"))) == 1


def test_commit_succeeds_then_raises_never_compensates_canonical_target(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    source_key = db_session.get(ServiceOrder, order_id).audio_object_key
    monkeypatch.setattr("server.routers.orders.transcribe_audio", successful_asr)
    original_commit = db_session.commit
    original_get = db_session.get
    commit_count = 0
    verification_reads_fail = False

    def commit_then_raise_connection_error() -> None:
        nonlocal commit_count, verification_reads_fail
        commit_count += 1
        if commit_count == 2:
            original_commit()
            verification_reads_fail = True
            raise ConnectionError("database outcome unknown")
        original_commit()

    def fail_verification_reads(model, identity):
        if verification_reads_fail:
            raise ConnectionError("verification unavailable")
        return original_get(model, identity)

    monkeypatch.setattr(db_session, "commit", commit_then_raise_connection_error)
    monkeypatch.setattr(db_session, "get", fail_verification_reads)
    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert response.status_code == 503
    assert response.json() == {"detail": "录音处理状态保存失败，请稍后重试"}

    monkeypatch.setattr(db_session, "commit", original_commit)
    monkeypatch.setattr(db_session, "get", original_get)
    db_session.rollback()
    db_session.expire_all()
    persisted = db_session.get(ServiceOrder, order_id)
    target_key = lifecycle_storage.copies[0][1]
    assert persisted.audio_object_key == target_key
    assert persisted.transcription_status == "succeeded"
    assert persisted.audio_delete_after is not None
    assert lifecycle_storage.exists(source_key)
    assert lifecycle_storage.exists(target_key)

    assert retry_storage_cleanup(db_session, lifecycle_storage) == {"succeeded": 1, "failed": 0}
    assert not lifecycle_storage.exists(source_key)
    assert lifecycle_storage.exists(target_key)
