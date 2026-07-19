import base64
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from server.models import CustomerAcceptance, ServiceOrder
from server.storage import LocalStorage


SIGNATURE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture
def share_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalStorage:
    storage = LocalStorage(tmp_path / "share-storage", signing_secret="share-test-secret")
    monkeypatch.setattr("server.routers.orders.get_storage", lambda: storage)
    return storage


def create_share(client, headers: dict[str, str], order_id: str) -> str:
    response = client.post(
        f"/api/v1/service-orders/{order_id}/customer-share",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["expires_in"] == 30 * 24 * 60 * 60
    return response.json()["share_token"]


def test_owner_creates_share_for_waiting_order_and_public_reads_limited_fields(
    client,
    auth_headers,
    create_order,
) -> None:
    headers = auth_headers("customer-share-owner")
    order = create_order(headers, status="waiting_acceptance")
    updated = client.patch(
        f"/api/v1/service-orders/{order['id']}",
        headers=headers,
        json={"transcript": "内部语音转写不能提供给客户"},
    )
    assert updated.status_code == 200

    token = create_share(client, headers, order["id"])
    response = client.get(f"/api/v1/service-orders/customer-share/{token}")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["id"] == order["id"]
    assert payload["customer_name"] == order["customer_name"]
    assert payload["status"] == "waiting_acceptance"
    assert "customer_phone" not in payload
    assert "transcript" not in payload
    assert "audio_url" not in payload
    assert "transcription_error" not in payload


def test_share_creation_is_owner_scoped_and_requires_acceptance_state(
    client,
    auth_headers,
    create_order,
) -> None:
    owner_headers = auth_headers("share-state-owner")
    stranger_headers = auth_headers("share-state-stranger")
    draft = create_order(owner_headers, status="draft")

    wrong_state = client.post(
        f"/api/v1/service-orders/{draft['id']}/customer-share",
        headers=owner_headers,
    )
    hidden = client.post(
        f"/api/v1/service-orders/{draft['id']}/customer-share",
        headers=stranger_headers,
    )
    anonymous = client.post(f"/api/v1/service-orders/{draft['id']}/customer-share")

    assert wrong_state.status_code == 409
    assert hidden.status_code == 404
    assert anonymous.status_code == 401


def test_tampered_share_token_is_rejected_without_order_disclosure(
    client,
    auth_headers,
    create_order,
) -> None:
    headers = auth_headers("share-tamper-owner")
    order = create_order(headers, status="waiting_acceptance")
    token = create_share(client, headers, order["id"])
    header, payload, signature = token.split(".")
    replacement = "a" if signature[0] != "a" else "b"
    tampered = f"{header}.{payload}.{replacement}{signature[1:]}"

    response = client.get(f"/api/v1/service-orders/customer-share/{tampered}")

    assert response.status_code == 404
    assert response.json() == {"detail": "客户验收链接无效或已过期"}


def test_shared_photo_is_readable_without_technician_authentication(
    client,
    auth_headers,
    create_order,
    share_storage: LocalStorage,
) -> None:
    del share_storage
    headers = auth_headers("share-photo-owner")
    order = create_order(headers, status="waiting_acceptance")
    uploaded = client.post(
        f"/api/v1/service-orders/{order['id']}/photos",
        headers=headers,
        data={"phase": "before"},
        files={"file": ("before.png", SIGNATURE_PNG, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    token = create_share(client, headers, order["id"])

    shared = client.get(f"/api/v1/service-orders/customer-share/{token}").json()
    photo_url = shared["before_photos"][0]["file_url"]
    photo = client.get(photo_url)

    assert photo.status_code == 200
    assert photo.content == SIGNATURE_PNG


def test_customer_accepts_shared_order_without_authentication(
    client,
    auth_headers,
    create_order,
    share_storage: LocalStorage,
    db_session: Session,
) -> None:
    headers = auth_headers("share-accept-owner")
    order = create_order(headers, status="waiting_acceptance")
    token = create_share(client, headers, order["id"])

    response = client.post(
        f"/api/v1/service-orders/customer-share/{token}/acceptance",
        data={"accepted": "true"},
        files={"signature": ("signature.png", SIGNATURE_PNG, "image/png")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "accepted"
    db_session.expire_all()
    assert db_session.get(ServiceOrder, order["id"]).status == "accepted"
    acceptance = db_session.query(CustomerAcceptance).filter_by(
        service_order_id=order["id"]
    ).one()
    assert share_storage.exists(acceptance.signature_object_key)

    duplicate = client.post(
        f"/api/v1/service-orders/customer-share/{token}/acceptance",
        data={"accepted": "true"},
        files={"signature": ("signature.png", SIGNATURE_PNG, "image/png")},
    )
    assert duplicate.status_code == 409
