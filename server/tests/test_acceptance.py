import base64
from pathlib import Path
import time
from urllib.parse import parse_qs, urlparse

import pytest
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
        "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////"
        "////////////////2wBDAf//////////////////////////////////////////////////////////////"
        "////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAU"
        "EAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgB"
        "AQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAA"
        "AP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAA"
        "AAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABB//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgB"
        "AwEBPxB//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPxB//8QAFBABAAAAAAAAAAAAAAAAAAAA"
        "AP/aAAgBAQABPxB//9k="
    )


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
