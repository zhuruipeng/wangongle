import base64
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from server.schemas import AiReportSourceValue, AiServiceReportDraft
from server.services.ai_report_generator import AiReportGenerationResult
from server.settings import AiReportSettings


CONFIGURED = AiReportSettings(
    enabled=True,
    api_key="mock-api-key",
    base_url="https://example.invalid/v1",
    model="qwen3.5-plus-2026-02-15",
)

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def report_payload() -> dict:
    return {
        "service_title": "空调安装服务报告",
        "service_type": "空调安装",
        "work_summary": "完成空调安装，试机正常。",
        "before_status": "安装前空调未固定。",
        "after_status": "安装完成后已试机。",
        "completed_items": [{"content": "完成空调安装", "source": "user_text"}],
        "materials": [{
            "name": {"value": "铜管", "source": "user_text"},
            "quantity": {"value": "2米", "source": "user_text"},
            "amount_cents": {"value": None, "source": "unknown"},
        }],
        "labor": [{
            "description": {"value": "安装服务", "source": "user_text"},
            "hours": {"value": None, "source": "unknown"},
            "amount_cents": {"value": None, "source": "unknown"},
        }],
        "risks": [],
        "exceptions": [],
        "customer_confirmation_text": "请客户确认本次空调安装已完成。",
        "needs_confirmation": ["铜管费用未提供，需要师傅确认"],
    }


def upload_photo(client, headers: dict[str, str], order_id: str, phase: str) -> None:
    response = client.post(
        f"/api/v1/service-orders/{order_id}/photos",
        headers=headers,
        data={"phase": phase},
        files={"file": (f"{phase}.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 201, response.text


def test_ai_report_schema_requires_unknown_values_to_stay_null() -> None:
    payload = report_payload()
    payload["materials"][0]["amount_cents"] = {"value": 12000, "source": "unknown"}

    with pytest.raises(ValidationError):
        AiServiceReportDraft.model_validate(payload)


def test_ai_report_schema_accepts_manual_input_source() -> None:
    value = AiReportSourceValue.model_validate({"value": "客户补充外机位置偏高", "source": "manual_input"})

    assert value.value == "客户补充外机位置偏高"
    assert value.source == "manual_input"


def test_ai_report_endpoint_uses_photos_text_and_persists_structured_json(
    client,
    auth_headers,
    create_order,
) -> None:
    headers = auth_headers("ai-report-owner", technician_name="王师傅")
    order = create_order(headers, service_type="空调安装")
    order_id = order["id"]
    transcript = "完成空调安装，用了两米铜管，试机正常。"
    patched = client.patch(
        f"/api/v1/service-orders/{order_id}",
        headers=headers,
        json={"transcript": transcript},
    )
    assert patched.status_code == 200, patched.text
    upload_photo(client, headers, order_id, "before")
    upload_photo(client, headers, order_id, "after")
    generated_report = AiServiceReportDraft.model_validate(report_payload())

    with patch("server.routers.orders.get_ai_report_settings", return_value=CONFIGURED), patch(
        "server.routers.orders.generate_ai_service_report",
        return_value=AiReportGenerationResult(report=generated_report),
    ) as generator:
        response = client.post(
            f"/api/v1/service-orders/{order_id}/ai-report",
            headers=headers,
            json={"manual_text": "客户补充外机位置偏高"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["report"]["materials"][0]["amount_cents"] == {"value": None, "source": "unknown"}
    assert body["report"]["needs_confirmation"] == ["铜管费用未提供，需要师傅确认"]
    call_kwargs = generator.call_args.kwargs
    assert call_kwargs["service_type"] == "空调安装"
    assert call_kwargs["transcript"] == transcript
    assert call_kwargs["manual_text"] == "客户补充外机位置偏高"
    assert len(call_kwargs["before_photo_urls"]) == 1
    assert len(call_kwargs["after_photo_urls"]) == 1

    detail = client.get(f"/api/v1/service-orders/{order_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["ai_report"]["service_title"] == "空调安装服务报告"

    edited = report_payload()
    edited["work_summary"] = "师傅已确认并修正报告草稿。"
    saved = client.put(f"/api/v1/service-orders/{order_id}/ai-report", headers=headers, json=edited)
    assert saved.status_code == 200, saved.text
    assert saved.json()["ai_report"]["work_summary"] == "师傅已确认并修正报告草稿。"


def test_ai_report_requires_before_and_after_photos(client, auth_headers, create_order) -> None:
    headers = auth_headers("ai-report-no-photos", technician_name="王师傅")
    order = create_order(headers)
    response = client.patch(
        f"/api/v1/service-orders/{order['id']}",
        headers=headers,
        json={"transcript": "完成空调清洗"},
    )
    assert response.status_code == 200, response.text

    with patch("server.routers.orders.generate_ai_service_report") as generator:
        response = client.post(f"/api/v1/service-orders/{order['id']}/ai-report", headers=headers)

    assert response.status_code == 400
    assert "照片" in response.json()["detail"]
    generator.assert_not_called()
