import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from server.database import SessionLocal, UPLOAD_DIR, engine
from server.main import app
from server.migrations import migrate
from server.models import ServiceAcceptance, ServiceAcceptanceLink
from server.services.acceptance import (
    ACCEPTANCE_STATEMENT,
    ACCEPTANCE_VERSION,
    build_snapshot_hash,
    hash_acceptance_token,
)


client = TestClient(app)
PNG_BYTES = b"\x89PNG\r\n\x1a\nmock-signature"


def create_ready_order() -> tuple[str, str]:
    response = client.post("/api/v1/service-orders", json={
        "order_no": f"ACCEPT-{uuid4().hex[:12]}",
        "company_name": "安心空调服务",
        "customer_name": "王先生",
        "customer_phone": "13812346688",
        "service_address": "临沂市兰山区金雀山路",
        "service_type": "1.5匹壁挂空调安装",
        "technician_name": "张师傅",
        "status": "in_progress",
    })
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    report = {
        "completed_items": ["已完成空调安装", "抽真空十五分钟，试机正常"],
        "materials": [{"name": "铜管", "quantity": "2米", "amount_cents": 16000}],
        "fee_items": [{"name": "安装服务费", "amount_cents": 15000}],
        "risks": ["室外机安装位置较高"],
        "after_sales_reminder": "建议一年后清洗",
        "total_amount_cents": 1,
        "paid_amount_cents": 0,
    }
    response = client.put(f"/api/v1/service-orders/{order_id}/report", json=report)
    assert response.status_code == 200 and response.json()["total_amount_cents"] == 31000, response.text
    photo_ids: list[str] = []
    for phase in ("before", "after"):
        response = client.post(
            f"/api/v1/service-orders/{order_id}/photos",
            data={"phase": phase},
            files={"file": (f"{phase}.png", PNG_BYTES, "image/png")},
        )
        assert response.status_code == 201, response.text
        photo_ids.append(response.json()["id"])
    return order_id, photo_ids[0]


def create_link(order_id: str) -> tuple[str, str]:
    response = client.post(f"/api/v1/service-orders/{order_id}/acceptance-link")
    assert response.status_code == 200, response.text
    url = response.json()["url"]
    token = parse_qs(urlparse(url).query)["token"][0]
    assert token and order_id not in token and len(token) >= 40
    return token, response.json()["expires_at"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def confirm(token: str, *, include_signature: bool = True):
    files = {"signature": ("signature.png", PNG_BYTES, "image/png")} if include_signature else None
    return client.post(
        "/api/v1/public/acceptance/confirm",
        headers=auth(token),
        data={
            "signer_name": "王先生",
            "acceptance_statement_version": ACCEPTANCE_VERSION,
            "confirmed": "true",
        },
        files=files,
    )


def run() -> None:
    migrate(engine)
    migrate(engine)

    # 1-2. Create a valid link; creating another revokes the old one immediately.
    rotating_id, _ = create_ready_order()
    old_token, expires_at = create_link(rotating_id)
    assert datetime.fromisoformat(expires_at) > datetime.now(timezone.utc)
    with SessionLocal() as db:
        stored_link = db.scalar(select(ServiceAcceptanceLink).where(
            ServiceAcceptanceLink.token_hash == hash_acceptance_token(old_token)
        ))
        assert stored_link is not None and stored_link.token_hash != old_token
    new_token, _ = create_link(rotating_id)
    response = client.get("/api/v1/public/acceptance", headers=auth(old_token))
    assert response.status_code == 410 and "撤销" in response.json()["detail"]
    assert client.get("/api/v1/public/acceptance", headers=auth(new_token)).status_code == 200

    # 3. An invalid token cannot view any report data.
    response = client.get("/api/v1/public/acceptance", headers=auth("invalid-token"))
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"

    # 4. An expired token cannot confirm acceptance.
    expired_id, _ = create_ready_order()
    expired_token, _ = create_link(expired_id)
    with SessionLocal() as db:
        link = db.scalar(select(ServiceAcceptanceLink).where(
            ServiceAcceptanceLink.token_hash == hash_acceptance_token(expired_token)
        ))
        assert link is not None
        link.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    response = confirm(expired_token)
    assert response.status_code == 410 and "过期" in response.json()["detail"]

    # 5. A revoked token cannot confirm acceptance.
    revoked_id, _ = create_ready_order()
    revoked_token, _ = create_link(revoked_id)
    assert client.post(f"/api/v1/service-orders/{revoked_id}/acceptance-link/revoke").status_code == 200
    response = confirm(revoked_token)
    assert response.status_code == 410 and "撤销" in response.json()["detail"]

    # 6. Public data is an explicit whitelist and omits phone/audio/transcript/internal AI fields.
    accepted_id, before_photo_id = create_ready_order()
    accepted_token, _ = create_link(accepted_id)
    response = client.get("/api/v1/public/acceptance", headers=auth(accepted_token))
    assert response.status_code == 200, response.text
    public_data = response.json()
    forbidden = {
        "customer_phone", "audio_url", "transcript", "report_model", "report_generation_status",
        "report_generation_error", "asr_request_id", "signature_file_url", "snapshot_hash",
        "token_hash", "service_order_id",
    }
    assert forbidden.isdisjoint(public_data)
    assert "13812346688" not in json.dumps(public_data, ensure_ascii=False)

    # 7. Missing signature is rejected.
    response = confirm(accepted_token, include_signature=False)
    assert response.status_code == 422

    # 8-9. A PNG signature accepts once, persists the immutable snapshot, and duplicates stay single-row.
    response = confirm(accepted_token)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted" and response.json()["accepted_at"]
    response = confirm(accepted_token)
    assert response.status_code == 409 and "已经验收" in response.json()["detail"]
    response = client.get("/api/v1/public/acceptance", headers=auth(accepted_token))
    assert response.status_code == 200 and response.json()["status"] == "accepted"
    detail = client.get(f"/api/v1/service-orders/{accepted_id}").json()
    assert detail["status"] == "accepted" and detail["accepted_at"]
    with SessionLocal() as db:
        count = db.scalar(select(func.count()).select_from(ServiceAcceptance).where(
            ServiceAcceptance.service_order_id == accepted_id
        ))
        acceptance = db.scalar(select(ServiceAcceptance).where(ServiceAcceptance.service_order_id == accepted_id))
        assert count == 1 and acceptance is not None
        assert len(acceptance.snapshot_hash) == 64
        assert (UPLOAD_DIR / acceptance.signature_file_url.removeprefix("/uploads/")).is_file()
        photos_snapshot = json.loads(acceptance.photos_snapshot_json)
        assert all(len(item["file_sha256"]) == 64 for item in photos_snapshot)

    # 10. Accepted reports and photos are locked against mutation.
    locked_report = {
        "completed_items": ["篡改"], "materials": [], "fee_items": [], "risks": [],
        "after_sales_reminder": "", "total_amount_cents": 0, "paid_amount_cents": 0,
    }
    assert client.put(f"/api/v1/service-orders/{accepted_id}/report", json=locked_report).status_code == 409
    response = client.post(
        f"/api/v1/service-orders/{accepted_id}/photos",
        data={"phase": "after"},
        files={"file": ("after.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 409
    assert client.delete(f"/api/v1/service-orders/{accepted_id}/photos/{before_photo_id}").status_code == 409

    # 11. Stable canonical JSON produces the same snapshot hash for identical inputs.
    report_snapshot = {"b": 2, "a": [1, {"z": "值"}]}
    photo_snapshot = [{"sort_order": 0, "phase": "before", "file_sha256": "a" * 64, "file_url": "/x"}]
    accepted_at = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    arguments = dict(
        signer_name="王先生", statement_text=ACCEPTANCE_STATEMENT,
        acceptance_version=ACCEPTANCE_VERSION, accepted_at=accepted_at,
        signature_sha256="b" * 64,
    )
    first = build_snapshot_hash(report_snapshot, photo_snapshot, **arguments)
    second = build_snapshot_hash({"a": [1, {"z": "值"}], "b": 2}, photo_snapshot, **arguments)
    assert first == second and len(first) == 64

    print("acceptance tests passed: token rotation/auth, public whitelist, signature, idempotency, locking, snapshot hash")


if __name__ == "__main__":
    run()
