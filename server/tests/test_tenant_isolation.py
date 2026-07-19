import base64

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models import AuditEvent, User
from server.schemas import ServiceOrderCreate
from server.tests.data import ORDER_PAYLOAD

REPORT_PAYLOAD = {
    "completed_items": ["已完成安装"],
    "materials": [{"name": "铜管", "quantity": "2米", "amount_cents": 16000}],
    "fee_items": [{"name": "安装服务费", "amount_cents": 15000}],
    "risks": [],
    "after_sales_reminder": "一年后保养",
    "total_amount_cents": 31000,
    "paid_amount_cents": 0,
}
AI_REPORT_PAYLOAD = {
    "service_title": "空调安装服务报告",
    "service_type": "空调安装",
    "work_summary": "完成空调安装。",
    "before_status": None,
    "after_status": None,
    "completed_items": [{"content": "完成空调安装", "source": "user_text"}],
    "materials": [],
    "labor": [],
    "risks": [],
    "exceptions": [],
    "customer_confirmation_text": None,
    "needs_confirmation": [],
}
SIGNATURE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_every_order_route_requires_authentication(client, auth_headers, create_order) -> None:
    owner = auth_headers("openid-owner")
    order_id = create_order(owner)["id"]
    requests = [
        client.post("/api/v1/service-orders", json=ORDER_PAYLOAD),
        client.get("/api/v1/service-orders"),
        client.get(f"/api/v1/service-orders/{order_id}"),
        client.patch(f"/api/v1/service-orders/{order_id}", json={"status": "cancelled"}),
        client.post(
            f"/api/v1/service-orders/{order_id}/photos",
            data={"phase": "before"},
            files={"file": ("before.jpg", b"photo", "image/jpeg")},
        ),
        client.delete(f"/api/v1/service-orders/{order_id}/photos/missing-photo"),
        client.post(
            f"/api/v1/service-orders/{order_id}/audio",
            files={"file": ("voice.mp3", b"ID3-audio", "audio/mpeg")},
        ),
        client.post(f"/api/v1/service-orders/{order_id}/transcribe"),
        client.post(f"/api/v1/service-orders/{order_id}/ai-report"),
        client.put(f"/api/v1/service-orders/{order_id}/ai-report", json=AI_REPORT_PAYLOAD),
        client.post(f"/api/v1/service-orders/{order_id}/generate-report"),
        client.put(f"/api/v1/service-orders/{order_id}/report", json=REPORT_PAYLOAD),
        client.post(f"/api/v1/service-orders/{order_id}/submit-acceptance"),
    ]
    assert [response.status_code for response in requests] == [401] * len(requests)


def test_other_user_cannot_discover_or_mutate_order(client, auth_headers, create_order) -> None:
    owner = auth_headers("openid-owner")
    stranger = auth_headers("openid-stranger")
    order_id = create_order(owner, transcript="完成空调安装")["id"]
    photo = client.post(
        f"/api/v1/service-orders/{order_id}/photos",
        headers=owner,
        data={"phase": "before"},
        files={"file": ("before.jpg", b"photo", "image/jpeg")},
    )
    assert photo.status_code == 201, photo.text

    responses = [
        client.get(f"/api/v1/service-orders/{order_id}", headers=stranger),
        client.patch(
            f"/api/v1/service-orders/{order_id}",
            headers=stranger,
            json={"service_type": "恶意修改"},
        ),
        client.patch(
            f"/api/v1/service-orders/{order_id}",
            headers=stranger,
            json={"status": "cancelled"},
        ),
        client.post(
            f"/api/v1/service-orders/{order_id}/photos",
            headers=stranger,
            data={"phase": "after"},
            files={"file": ("after.jpg", b"photo", "image/jpeg")},
        ),
        client.delete(
            f"/api/v1/service-orders/{order_id}/photos/{photo.json()['id']}",
            headers=stranger,
        ),
        client.post(
            f"/api/v1/service-orders/{order_id}/audio",
            headers=stranger,
            files={"file": ("voice.mp3", b"ID3-audio", "audio/mpeg")},
        ),
        client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=stranger),
        client.post(f"/api/v1/service-orders/{order_id}/ai-report", headers=stranger),
        client.put(f"/api/v1/service-orders/{order_id}/ai-report", headers=stranger, json=AI_REPORT_PAYLOAD),
        client.post(f"/api/v1/service-orders/{order_id}/generate-report", headers=stranger),
        client.put(
            f"/api/v1/service-orders/{order_id}/report",
            headers=stranger,
            json=REPORT_PAYLOAD,
        ),
        client.post(f"/api/v1/service-orders/{order_id}/submit-acceptance", headers=stranger),
    ]
    assert [response.status_code for response in responses] == [404] * len(responses)
    assert client.get("/api/v1/service-orders", headers=stranger).json() == []


def test_owner_is_applied_in_sql_and_order_numbers_are_tenant_scoped(
    client,
    auth_headers,
    create_order,
    db_session: Session,
) -> None:
    first = auth_headers("openid-one", technician_name="王师傅")
    second = auth_headers("openid-two", technician_name="李师傅")

    first_order = create_order(first, technician_name="伪造姓名")
    second_order = create_order(second)

    assert first_order["technician_name"] == "王师傅"
    assert second_order["technician_name"] == "李师傅"
    assert first_order["order_no"] == second_order["order_no"] == "ORDER-001"
    assert client.post("/api/v1/service-orders", headers=first, json=ORDER_PAYLOAD).status_code == 409
    assert "technician_name" not in ServiceOrderCreate.model_fields

    rows = db_session.execute(
        select(User.openid, User.id).where(User.openid.in_(["openid-one", "openid-two"]))
    ).all()
    owner_ids = {openid: user_id for openid, user_id in rows}
    from server.models import ServiceOrder

    assert db_session.get(ServiceOrder, first_order["id"]).owner_user_id == owner_ids["openid-one"]
    assert db_session.get(ServiceOrder, second_order["id"]).owner_user_id == owner_ids["openid-two"]


def test_incomplete_profile_cannot_create_order(client, auth_headers) -> None:
    headers = auth_headers("openid-incomplete", technician_name="")
    response = client.post("/api/v1/service-orders", headers=headers, json=ORDER_PAYLOAD)
    assert response.status_code == 403
    assert response.json() == {"detail": "请先完善师傅资料"}


def test_required_order_actions_write_minimal_audit_events(
    client,
    auth_headers,
    create_order,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services.report_generator import GeneratedReportResult
    from server.services.tencent_asr import TencentAsrResult
    from server.settings import AiReportSettings, AsrSettings

    owner = auth_headers("openid-audit", technician_name="审计师傅")
    order = create_order(owner, transcript="完成空调安装")
    order_id = order["id"]
    photo = client.post(
        f"/api/v1/service-orders/{order_id}/photos",
        headers=owner,
        data={"phase": "before"},
        files={"file": ("sensitive-customer-name.jpg", b"photo", "image/jpeg")},
    )
    assert photo.status_code == 201
    assert client.delete(
        f"/api/v1/service-orders/{order_id}/photos/{photo.json()['id']}", headers=owner
    ).status_code == 204
    assert client.post(
        f"/api/v1/service-orders/{order_id}/audio",
        headers=owner,
        files={"file": ("private-conversation.mp3", b"ID3-audio", "audio/mpeg")},
    ).status_code == 200

    monkeypatch.setattr(
        "server.routers.orders.get_asr_settings",
        lambda: AsrSettings(True, "id", "key", "ap-shanghai", "16k_zh", ""),
    )
    monkeypatch.setattr(
        "server.routers.orders.transcribe_audio",
        lambda path, settings: TencentAsrResult("敏感语音文本", "provider-request", 1000),
    )
    assert client.post(f"/api/v1/service-orders/{order_id}/transcribe", headers=owner).status_code == 200

    from server.schemas import GeneratedCompletedItem, GeneratedServiceReport

    generated_report = GeneratedReportResult(
        report=GeneratedServiceReport(
            summary="完成安装",
            completed_items=[GeneratedCompletedItem(content="完成安装", source_text="完成安装")],
            materials=[],
            labor_items=[],
            risks=[],
            after_sales=[],
            missing_information=[],
            warnings=[],
        ),
        total_amount_cents=0,
    )
    monkeypatch.setattr(
        "server.routers.orders.get_ai_report_settings",
        lambda: AiReportSettings(True, "key", "https://example.invalid", "mock-model"),
    )
    monkeypatch.setattr(
        "server.routers.orders.generate_service_report",
        lambda service_type, transcript, settings: generated_report,
    )
    assert client.post(
        f"/api/v1/service-orders/{order_id}/generate-report", headers=owner
    ).status_code == 200
    assert client.post(
        f"/api/v1/service-orders/{order_id}/submit-acceptance", headers=owner
    ).status_code == 200
    assert client.post(
        f"/api/v1/service-orders/{order_id}/acceptance",
        headers=owner,
        data={"accepted": "true"},
        files={"signature": ("signature.png", SIGNATURE_PNG, "image/png")},
    ).status_code == 201

    events = db_session.scalars(
        select(AuditEvent).where(AuditEvent.resource_id == order_id).order_by(AuditEvent.created_at)
    ).all()
    assert [(event.event_type, event.outcome) for event in events] == [
        ("order_created", "succeeded"),
        ("photo_uploaded", "succeeded"),
        ("photo_deleted", "succeeded"),
        ("audio_uploaded", "succeeded"),
        ("transcription", "succeeded"),
        ("report_generation", "succeeded"),
        ("acceptance_submitted", "succeeded"),
        ("acceptance", "succeeded"),
    ]
    assert {event.resource_type for event in events} == {"service_order"}
    assert {event.request_id for event in events}
    serialized = " ".join(
        str(value)
        for event in events
        for value in (
            event.user_id,
            event.resource_type,
            event.resource_id,
            event.request_id,
            event.event_type,
            event.outcome,
            event.created_at,
        )
    )
    for sensitive in (
        "敏感客户姓名",
        "13800000000",
        "敏感服务地址",
        "敏感语音文本",
        "sensitive-customer-name.jpg",
        "private-conversation.mp3",
        "provider-request",
    ):
        assert sensitive not in serialized
