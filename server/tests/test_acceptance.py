import base64
from pathlib import Path
import struct
import time
from urllib.parse import parse_qs, urlparse
import zlib

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from server.models import CustomerAcceptance, ServiceOrder, StorageCleanupJob
from server.storage import LocalStorage


@pytest.fixture
def acceptance_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalStorage:
    storage = LocalStorage(tmp_path / "acceptance-storage", signing_secret="acceptance-test-secret")
    monkeypatch.setattr("server.routers.orders.get_storage", lambda: storage)
    return storage


@pytest.fixture
def signature_png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


@pytest.fixture
def signature_jpeg() -> bytes:
    return base64.b64decode(
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
        "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
        "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIA"
        "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQA"
        "AAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3"
        "ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWm"
        "p6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEA"
        "AwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSEx"
        "BhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElK"
        "U1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3"
        "uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iii"
        "gD//2Q=="
    )


@pytest.fixture
def crc_valid_but_undecodable_png() -> bytes:
    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", b"not-a-zlib-stream")
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def malformed_jpeg_truncated_sos(signature_jpeg: bytes) -> bytes:
    start = signature_jpeg.index(b"\xff\xda")
    segment_length = int.from_bytes(signature_jpeg[start + 2:start + 4], "big")
    scan_data_start = start + 2 + segment_length
    return signature_jpeg[:scan_data_start - 1] + b"\xff\xd9"


@pytest.fixture
def jpeg_with_app_payload_containing_sos_marker(signature_jpeg: bytes) -> bytes:
    payload = b"Exif\x00\x00opaque-marker:\xff\xda\x00\x01-not-a-real-sos"
    app1 = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    return signature_jpeg[:2] + app1 + signature_jpeg[2:]


@pytest.fixture
def owner_order(client, auth_headers, create_order):
    sequence = 0

    def create(*, status: str = "waiting_acceptance"):
        nonlocal sequence
        sequence += 1
        headers = auth_headers(f"acceptance-owner-{sequence}")
        order_id = create_order(headers, status=status)["id"]
        return order_id, headers

    return create


def post_acceptance(client, order_id: str, headers: dict[str, str], content: bytes, **overrides):
    filename = overrides.pop("filename", "signature.png")
    content_type = overrides.pop("content_type", "image/png")
    accepted = overrides.pop("accepted", "true")
    assert not overrides
    return client.post(
        f"/api/v1/service-orders/{order_id}/acceptance",
        headers=headers,
        data={"accepted": accepted},
        files={"signature": (filename, content, content_type)},
    )


def test_owner_persists_acceptance_and_returns_owner_authorized_signed_url(
    client,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order()
    monkeypatch.setenv("COS_PRESIGNED_SECONDS", "120")

    response = post_acceptance(client, order_id, headers, signature_png)

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["acceptance"]["accepted_at"]
    signature_url = payload["acceptance"]["signature_url"]
    parsed = urlparse(signature_url)
    assert parsed.path.startswith("/api/v1/service-orders/private-files/")
    expires_at = int(parse_qs(parsed.query)["expires"][0])
    assert 299 <= expires_at - int(time.time()) <= 300
    assert parse_qs(parsed.query)["signature"]
    assert client.get(signature_url, headers=headers).content == signature_png

    acceptance = db_session.query(CustomerAcceptance).filter_by(service_order_id=order_id).one()
    assert acceptance.signature_object_key.startswith("test/users/")
    assert f"/orders/{order_id}/signatures/" in acceptance.signature_object_key
    assert acceptance_storage.exists(acceptance.signature_object_key)
    assert db_session.get(ServiceOrder, order_id).status == "accepted"


def test_acceptance_requires_true_checkbox_and_waiting_state(
    client,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
) -> None:
    order_id, headers = owner_order()
    rejected = post_acceptance(client, order_id, headers, signature_png, accepted="false")
    assert rejected.status_code == 422

    alias_id, alias_headers = owner_order()
    alias = post_acceptance(client, alias_id, alias_headers, signature_png, accepted="yes")
    assert alias.status_code == 422

    draft_id, draft_headers = owner_order(status="draft")
    wrong_state = post_acceptance(client, draft_id, draft_headers, signature_png)
    assert wrong_state.status_code == 409
    assert list(acceptance_storage.root.rglob("*.png")) == []


@pytest.mark.parametrize(
    ("fixture_name", "filename", "content_type"),
    [
        ("signature_png", "signature.png", "image/png"),
        ("signature_jpeg", "signature.jpg", "image/jpeg"),
    ],
)
def test_acceptance_accepts_structurally_valid_png_and_jpeg(
    client,
    owner_order,
    acceptance_storage: LocalStorage,
    request: pytest.FixtureRequest,
    fixture_name: str,
    filename: str,
    content_type: str,
) -> None:
    del acceptance_storage
    order_id, headers = owner_order()
    response = post_acceptance(
        client,
        order_id,
        headers,
        request.getfixturevalue(fixture_name),
        filename=filename,
        content_type=content_type,
    )
    assert response.status_code == 201, response.text


def test_acceptance_allows_valid_jpeg_with_sos_bytes_inside_app_payload(
    client,
    owner_order,
    jpeg_with_app_payload_containing_sos_marker: bytes,
    acceptance_storage: LocalStorage,
) -> None:
    del acceptance_storage
    order_id, headers = owner_order()
    response = post_acceptance(
        client,
        order_id,
        headers,
        jpeg_with_app_payload_containing_sos_marker,
        filename="signature.jpg",
        content_type="image/jpeg",
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("signature.gif", "image/gif"),
        ("signature.png", "image/jpeg"),
        ("signature.exe", "image/png"),
    ],
)
def test_acceptance_rejects_mime_extension_mismatch_and_unsupported_types(
    client,
    owner_order,
    acceptance_storage: LocalStorage,
    filename: str,
    content_type: str,
) -> None:
    order_id, headers = owner_order()
    response = post_acceptance(
        client,
        order_id,
        headers,
        b"not-an-image",
        filename=filename,
        content_type=content_type,
    )
    assert response.status_code == 415
    assert list(acceptance_storage.root.rglob("*.*")) == []


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("signature.png", "image/png"), ("signature.jpg", "image/jpeg")],
)
def test_acceptance_rejects_arbitrary_bytes_with_image_name_and_mime(
    client,
    owner_order,
    acceptance_storage: LocalStorage,
    db_session: Session,
    filename: str,
    content_type: str,
) -> None:
    order_id, headers = owner_order()
    response = post_acceptance(
        client,
        order_id,
        headers,
        b"arbitrary-signature-bytes",
        filename=filename,
        content_type=content_type,
    )
    assert response.status_code == 415
    assert db_session.query(CustomerAcceptance).filter_by(service_order_id=order_id).count() == 0
    assert list(acceptance_storage.root.rglob("*.*")) == []


@pytest.mark.parametrize(
    ("fixture_name", "filename", "content_type"),
    [
        ("crc_valid_but_undecodable_png", "signature.png", "image/png"),
        ("malformed_jpeg_truncated_sos", "signature.jpg", "image/jpeg"),
    ],
)
def test_acceptance_rejects_structured_but_undecodable_images(
    client,
    owner_order,
    acceptance_storage: LocalStorage,
    db_session: Session,
    request: pytest.FixtureRequest,
    fixture_name: str,
    filename: str,
    content_type: str,
) -> None:
    order_id, headers = owner_order()
    response = post_acceptance(
        client,
        order_id,
        headers,
        request.getfixturevalue(fixture_name),
        filename=filename,
        content_type=content_type,
    )
    assert response.status_code == 415
    assert db_session.query(CustomerAcceptance).filter_by(service_order_id=order_id).count() == 0
    assert list(acceptance_storage.root.rglob("*.*")) == []


def test_acceptance_rejects_signature_over_five_megabytes(
    client,
    owner_order,
    acceptance_storage: LocalStorage,
) -> None:
    order_id, headers = owner_order()
    response = post_acceptance(client, order_id, headers, b"x" * (5 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert list(acceptance_storage.root.rglob("*.png")) == []


def test_acceptance_is_owner_scoped_and_requires_authentication(
    client,
    auth_headers,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
) -> None:
    order_id, _owner_headers = owner_order()
    stranger = auth_headers("acceptance-stranger")
    hidden = post_acceptance(client, order_id, stranger, signature_png)
    anonymous = client.post(
        f"/api/v1/service-orders/{order_id}/acceptance",
        data={"accepted": "true"},
        files={"signature": ("signature.png", signature_png, "image/png")},
    )
    assert hidden.status_code == 404
    assert anonymous.status_code == 401
    assert list(acceptance_storage.root.rglob("*.png")) == []


def test_duplicate_acceptance_returns_conflict_without_second_signature(
    client,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
    db_session: Session,
) -> None:
    order_id, headers = owner_order()
    first = post_acceptance(client, order_id, headers, signature_png)
    duplicate = post_acceptance(client, order_id, headers, signature_png)
    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert db_session.query(CustomerAcceptance).filter_by(service_order_id=order_id).count() == 1
    assert len(list(acceptance_storage.root.rglob("*.png"))) == 1


def test_acceptance_db_failure_deletes_uploaded_signature(
    client,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order()
    monkeypatch.setattr(
        "server.routers.orders.add_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db write failed")),
    )
    response = post_acceptance(client, order_id, headers, signature_png)
    assert response.status_code == 500
    assert list(acceptance_storage.root.rglob("*.png")) == []


def test_acceptance_cleanup_failure_enqueues_safe_outbox_job(
    client,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order()
    monkeypatch.setattr(
        "server.routers.orders.add_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db write failed")),
    )
    monkeypatch.setattr(
        acceptance_storage,
        "delete",
        lambda key: (_ for _ in ()).throw(RuntimeError("provider credential must not leak")),
    )
    response = post_acceptance(client, order_id, headers, signature_png)
    assert response.status_code == 500
    assert "provider credential" not in response.text
    job = db_session.query(StorageCleanupJob).one()
    assert job.source == "acceptance_upload_rollback"
    assert f"/orders/{order_id}/signatures/" in job.object_key


def test_acceptance_partial_upload_failure_uses_cleanup_outbox(
    client,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order()
    original_put = acceptance_storage.put

    def partial_put(key, stream, content_type) -> None:
        original_put(key, stream, content_type)
        raise RuntimeError("provider credential must not leak")

    monkeypatch.setattr(acceptance_storage, "put", partial_put)
    monkeypatch.setattr(
        acceptance_storage,
        "delete",
        lambda key: (_ for _ in ()).throw(RuntimeError("provider credential must not leak")),
    )
    response = post_acceptance(client, order_id, headers, signature_png)
    assert response.status_code == 503
    assert "provider credential" not in response.text
    job = db_session.query(StorageCleanupJob).one()
    assert job.source == "acceptance_upload_rollback"
    assert f"/orders/{order_id}/signatures/" in job.object_key


def test_acceptance_presign_failure_compensates_before_db_commit(
    client,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order()
    monkeypatch.setattr(
        acceptance_storage,
        "presigned_get_url",
        lambda key, expires: (_ for _ in ()).throw(
            RuntimeError("presign provider credential must not leak")
        ),
    )
    response = post_acceptance(client, order_id, headers, signature_png)
    assert response.status_code == 503
    assert response.json() == {"detail": "签名授权失败，请稍后重试"}
    assert "credential" not in response.text
    db_session.expire_all()
    assert db_session.query(CustomerAcceptance).filter_by(service_order_id=order_id).count() == 0
    assert db_session.get(ServiceOrder, order_id).status == "waiting_acceptance"
    assert list(acceptance_storage.root.rglob("*.png")) == []


def test_accepted_status_only_comes_from_acceptance_and_cannot_reopen(
    client,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
    db_session: Session,
) -> None:
    del acceptance_storage
    order_id, headers = owner_order()
    direct = client.patch(
        f"/api/v1/service-orders/{order_id}",
        headers=headers,
        json={"status": "accepted"},
    )
    assert direct.status_code == 422
    assert db_session.get(ServiceOrder, order_id).status == "waiting_acceptance"
    assert db_session.query(CustomerAcceptance).filter_by(service_order_id=order_id).count() == 0

    accepted = post_acceptance(client, order_id, headers, signature_png)
    assert accepted.status_code == 201
    reopened = client.patch(
        f"/api/v1/service-orders/{order_id}",
        headers=headers,
        json={"status": "draft"},
    )
    assert reopened.status_code == 409
    db_session.expire_all()
    assert db_session.get(ServiceOrder, order_id).status == "accepted"


def test_order_cannot_be_created_as_already_accepted(
    client,
    auth_headers,
) -> None:
    from server.tests.data import ORDER_PAYLOAD

    headers = auth_headers("create-accepted-forbidden")
    response = client.post(
        "/api/v1/service-orders",
        headers=headers,
        json={**ORDER_PAYLOAD, "status": "accepted"},
    )
    assert response.status_code == 422


def test_acceptance_atomic_status_race_rolls_back_and_compensates_signature(
    client,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order()
    original_presign = acceptance_storage.presigned_get_url

    def cancel_before_terminal_update(key: str, expires: int) -> str:
        with Session(bind=db_session.get_bind()) as competing:
            competing.execute(
                update(ServiceOrder)
                .where(ServiceOrder.id == order_id)
                .values(status="cancelled")
            )
            competing.commit()
        return original_presign(key, expires)

    monkeypatch.setattr(
        acceptance_storage,
        "presigned_get_url",
        cancel_before_terminal_update,
    )
    response = post_acceptance(client, order_id, headers, signature_png)
    assert response.status_code == 409
    db_session.expire_all()
    assert db_session.get(ServiceOrder, order_id).status == "cancelled"
    assert db_session.query(CustomerAcceptance).filter_by(service_order_id=order_id).count() == 0
    assert list(acceptance_storage.root.rglob("*.png")) == []


def test_acceptance_success_does_not_refresh_after_commit(
    client,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del acceptance_storage
    order_id, headers = owner_order()
    monkeypatch.setattr(
        db_session,
        "refresh",
        lambda instance: (_ for _ in ()).throw(AssertionError("post-commit refresh forbidden")),
    )
    response = post_acceptance(client, order_id, headers, signature_png)
    assert response.status_code == 201, response.text
    assert response.json()["acceptance"]["id"]


def test_acceptance_commit_succeeds_then_raises_preserves_canonical_signature(
    client,
    owner_order,
    signature_png: bytes,
    acceptance_storage: LocalStorage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, headers = owner_order()
    original_commit = db_session.commit

    def commit_then_raise() -> None:
        original_commit()
        raise ConnectionError("acceptance commit outcome unknown")

    monkeypatch.setattr(db_session, "commit", commit_then_raise)
    response = post_acceptance(client, order_id, headers, signature_png)
    assert response.status_code == 503
    assert response.json() == {"detail": "验收状态保存失败，请稍后重试"}

    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.rollback()
    with Session(bind=db_session.get_bind()) as verification:
        order = verification.get(ServiceOrder, order_id)
        acceptance = verification.query(CustomerAcceptance).filter_by(
            service_order_id=order_id
        ).one()
        assert order.status == "accepted"
        assert acceptance.signature_object_key
        assert acceptance_storage.exists(acceptance.signature_object_key)
