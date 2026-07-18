from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models import AuditEvent, ServiceOrder
from server.services.speech_to_text import SpeechToTextError
from server.services.tencent_asr import TencentAsrResult
from server.settings import AsrSettings
from server.storage import LocalStorage


CONFIGURED_ASR = AsrSettings(True, "id", "key", "ap-shanghai", "16k_zh", "")


class TrackingStorage(LocalStorage):
    def __init__(self, root: Path) -> None:
        super().__init__(root, signing_secret="audio-lifecycle-test-secret")
        self.moves: list[tuple[str, str]] = []
        self.fail_move = False
        self.fail_reverse_move = False

    def move(self, source_key: str, target_key: str) -> None:
        self.moves.append((source_key, target_key))
        if self.fail_move:
            raise RuntimeError("provider credential must not leak")
        if self.fail_reverse_move and "/audio-expiring/" in f"/{source_key}":
            raise RuntimeError("reverse provider credential must not leak")
        super().move(source_key, target_key)


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


def test_transcription_moves_audio_to_expiring_prefix_and_sets_deadline(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    before = datetime.now(timezone.utc)
    monkeypatch.setattr("server.routers.orders.transcribe_audio", successful_asr)

    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"
    source, target = lifecycle_storage.moves[0]
    assert "/audio-pending/" in f"/{source}"
    assert "/audio-expiring/" in f"/{target}"
    assert not lifecycle_storage.exists(source)
    assert lifecycle_storage.exists(target)
    order = db_session.get(ServiceOrder, order_id)
    assert order is not None
    assert order.audio_object_key == target
    assert order.audio_delete_after is not None
    assert order.audio_delete_after.tzinfo is not None
    assert before + timedelta(days=7) <= order.audio_delete_after <= datetime.now(timezone.utc) + timedelta(days=7)


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
    assert downloaded_path
    assert not downloaded_path[0].exists()
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
    assert lifecycle_storage.moves == []
    assert lifecycle_storage.exists(pending_key)
    assert db_session.get(ServiceOrder, order_id).audio_object_key == pending_key

    monkeypatch.setattr("server.routers.orders.transcribe_audio", successful_asr)
    retried = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["status"] == "succeeded"


def test_failed_storage_move_preserves_pending_source_and_uses_safe_error(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    pending_key = db_session.get(ServiceOrder, order_id).audio_object_key
    lifecycle_storage.fail_move = True
    monkeypatch.setattr("server.routers.orders.transcribe_audio", successful_asr)

    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)

    assert response.status_code == 503
    assert "provider credential" not in response.text
    db_session.expire_all()
    order = db_session.get(ServiceOrder, order_id)
    assert order.audio_object_key == pending_key
    assert order.audio_delete_after is None
    assert order.transcription_status == "failed"
    assert lifecycle_storage.exists(pending_key)
    assert not lifecycle_storage.exists(lifecycle_storage.moves[0][1])
    audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.resource_id == order_id,
            AuditEvent.event_type == "storage.audio_transition",
        )
    )
    assert audit is not None
    assert audit.outcome == "failed"


def test_uploading_new_audio_clears_previous_expiry_deadline(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del lifecycle_storage
    order_id, headers = owner_order(audio=True)
    monkeypatch.setattr("server.routers.orders.transcribe_audio", successful_asr)
    assert client.post(
        f"/api/v1/service-orders/{order_id}/transcribe", headers=headers
    ).status_code == 200
    assert db_session.get(ServiceOrder, order_id).audio_delete_after is not None

    replacement = client.post(
        f"/api/v1/service-orders/{order_id}/audio",
        headers=headers,
        files={"file": ("replacement.mp3", b"ID3-replacement", "audio/mpeg")},
    )

    assert replacement.status_code == 200
    assert db_session.get(ServiceOrder, order_id).audio_delete_after is None


def test_db_failure_after_move_restores_pending_audio_for_retry(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    pending_key = db_session.get(ServiceOrder, order_id).audio_object_key
    downloaded_path: list[Path] = []

    def capture_download(path: Path, settings: AsrSettings) -> TencentAsrResult:
        del settings
        downloaded_path.append(path)
        return TencentAsrResult("完成空调安装", "asr-request", 1200)

    monkeypatch.setattr("server.routers.orders.transcribe_audio", capture_download)
    original_commit = db_session.commit
    commit_count = 0

    def fail_final_commit_once() -> None:
        nonlocal commit_count
        commit_count += 1
        if commit_count == 2:
            raise RuntimeError("database credential must not leak")
        original_commit()

    monkeypatch.setattr(db_session, "commit", fail_final_commit_once)
    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)

    assert response.status_code == 503
    assert response.json() == {"detail": "录音处理状态保存失败，请稍后重试"}
    assert "credential" not in response.text
    db_session.expire_all()
    order = db_session.get(ServiceOrder, order_id)
    assert order.audio_object_key == pending_key
    assert order.audio_delete_after is None
    assert order.transcription_status == "failed"
    assert lifecycle_storage.exists(pending_key)
    expiring_key = lifecycle_storage.moves[0][1]
    assert not lifecycle_storage.exists(expiring_key)
    assert lifecycle_storage.moves[-1] == (expiring_key, pending_key)
    assert downloaded_path and not downloaded_path[0].exists()
    assert not downloaded_path[0].parent.exists()

    monkeypatch.setattr(db_session, "commit", original_commit)
    retried = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["status"] == "succeeded"


def test_reverse_move_failure_persists_target_recovery_key_and_safe_audit(
    client,
    owner_order,
    lifecycle_storage: TrackingStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order(audio=True)
    pending_key = db_session.get(ServiceOrder, order_id).audio_object_key
    lifecycle_storage.fail_reverse_move = True
    monkeypatch.setattr("server.routers.orders.transcribe_audio", successful_asr)
    original_commit = db_session.commit
    commit_count = 0

    def fail_final_commit_once() -> None:
        nonlocal commit_count
        commit_count += 1
        if commit_count == 2:
            raise RuntimeError("database credential must not leak")
        original_commit()

    monkeypatch.setattr(db_session, "commit", fail_final_commit_once)
    response = client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=headers)

    assert response.status_code == 503
    assert response.json() == {"detail": "录音处理状态保存失败，请稍后重试"}
    assert "credential" not in response.text
    db_session.expire_all()
    order = db_session.get(ServiceOrder, order_id)
    expiring_key = lifecycle_storage.moves[0][1]
    assert order.audio_object_key == expiring_key
    assert order.audio_object_key != pending_key
    assert order.audio_delete_after is not None
    assert order.transcription_status == "failed"
    assert not lifecycle_storage.exists(pending_key)
    assert lifecycle_storage.exists(expiring_key)
    audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.resource_id == order_id,
            AuditEvent.event_type == "storage.audio_transition",
            AuditEvent.outcome == "failed",
        )
    )
    assert audit is not None
