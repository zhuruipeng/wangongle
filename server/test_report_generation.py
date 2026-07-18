import json
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from server.main import app
from server.services.report_generator import (
    ReportGenerationError,
    generate_service_report,
    validate_and_recalculate,
)
from server.settings import AiReportSettings


client = TestClient(app)
CONFIGURED = AiReportSettings(
    enabled=True,
    api_key="mock-api-key",
    base_url="https://example.invalid/v1",
    model="qwen3.5-plus-2026-02-15",
)
UNCONFIGURED = AiReportSettings(
    enabled=True,
    api_key="",
    base_url="https://example.invalid/v1",
    model="qwen3.5-plus-2026-02-15",
)


def create_order(transcript: str | None) -> str:
    response = client.post("/api/v1/service-orders", json={
        "order_no": f"AI-{uuid4().hex[:12]}",
        "company_name": "测试公司",
        "customer_name": "测试客户",
        "customer_phone": "13800000000",
        "service_address": "测试地址",
        "service_type": "空调安装",
        "technician_name": "测试师傅",
        "status": "in_progress",
    })
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    if transcript is not None:
        response = client.patch(
            f"/api/v1/service-orders/{order_id}", json={"transcript": transcript}
        )
        assert response.status_code == 200, response.text
    return order_id


def report_payload(transcript: str) -> dict:
    return {
        "summary": "完成空调安装并试机",
        "completed_items": [{"content": "完成空调安装", "source_text": "完成空调安装"}],
        "materials": [{
            "name": "铜管",
            "quantity": 2,
            "unit": "米",
            "unit_price_cents": None,
            "amount_cents": None,
            "source_text": "用了两米铜管",
            "needs_confirmation": True,
        }],
        "labor_items": [{
            "name": "安装费",
            "amount_cents": 15000,
            "source_text": "安装费一百五十元",
            "needs_confirmation": True,
        }],
        "risks": [],
        "after_sales": [],
        "missing_information": ["铜管单价未说明"],
        "warnings": [],
    }


def expect_generation_error(raw_json: str, transcript: str) -> None:
    try:
        validate_and_recalculate(raw_json, transcript)
    except ReportGenerationError:
        return
    raise AssertionError("expected report validation to fail")


def run() -> None:
    transcript = "完成空调安装，用了两米铜管，安装费一百五十元。"
    valid_json = json.dumps(report_payload(transcript), ensure_ascii=False)

    # 1. Valid JSON is strictly validated, recalculated, returned, and persisted.
    order_id = create_order(transcript)
    generated = validate_and_recalculate(valid_json, transcript)
    with patch("server.main.get_ai_report_settings", return_value=CONFIGURED), patch(
        "server.main.generate_service_report", return_value=generated
    ):
        response = client.post(f"/api/v1/service-orders/{order_id}/generate-report")
    assert response.status_code == 200, response.text
    assert response.json()["total_amount_cents"] == 15000
    detail = client.get(f"/api/v1/service-orders/{order_id}").json()
    assert detail["report_generation_status"] == "succeeded"
    assert detail["generated_report"]["materials"][0]["amount_cents"] is None
    assert detail["report_model"] == "qwen3.5-plus-2026-02-15"

    # 2. Invalid JSON is rejected after at most one automatic retry.
    with patch(
        "server.services.report_generator.request_qwen_report", return_value="not-json"
    ) as request_mock:
        try:
            generate_service_report("空调安装", transcript, CONFIGURED)
        except ReportGenerationError:
            pass
        else:
            raise AssertionError("invalid JSON should fail")
    assert request_mock.call_count == 2
    invalid_id = create_order(transcript)
    with patch("server.main.get_ai_report_settings", return_value=CONFIGURED), patch(
        "server.main.generate_service_report",
        side_effect=ReportGenerationError("模型未返回有效JSON"),
    ):
        response = client.post(f"/api/v1/service-orders/{invalid_id}/generate-report")
    assert response.status_code == 502
    assert client.get(f"/api/v1/service-orders/{invalid_id}").json()["report_generation_status"] == "failed"

    # 3. Missing/extra fields and content without a transcript source are rejected.
    missing = report_payload(transcript)
    missing.pop("warnings")
    expect_generation_error(json.dumps(missing, ensure_ascii=False), transcript)
    extra = report_payload(transcript)
    extra["invented_warranty"] = "五年保修"
    expect_generation_error(json.dumps(extra, ensure_ascii=False), transcript)
    fabricated = report_payload(transcript)
    fabricated["after_sales"] = [{"content": "提供五年保修", "source_text": "提供五年保修"}]
    expect_generation_error(json.dumps(fabricated, ensure_ascii=False), transcript)

    # 4. Missing API key keeps the server healthy and returns a readable error.
    unconfigured_id = create_order(transcript)
    with patch("server.main.get_ai_report_settings", return_value=UNCONFIGURED):
        response = client.post(f"/api/v1/service-orders/{unconfigured_id}/generate-report")
    assert response.status_code == 503
    assert "AI" in response.json()["detail"]
    assert client.get("/api/health").status_code == 200

    # 5. Empty transcript is rejected before attempting a provider call.
    empty_id = create_order(None)
    response = client.post(f"/api/v1/service-orders/{empty_id}/generate-report")
    assert response.status_code == 400

    # 6. Unknown material price remains null and is never estimated into the total.
    no_price = validate_and_recalculate(valid_json, transcript)
    assert no_price.report.materials[0].unit_price_cents is None
    assert no_price.report.materials[0].amount_cents is None
    assert no_price.total_amount_cents == 15000

    print("AI report tests passed: success, invalid JSON/schema/source, unconfigured, empty transcript, no estimation")


if __name__ == "__main__":
    run()
