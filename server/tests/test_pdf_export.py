from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from server.storage import LocalStorage


REPORT_PAYLOAD = {
    "completed_items": ["完成旧机拆除", "安装新设备并完成通电测试"],
    "materials": [
        {"name": "铜管", "quantity": "3米", "amount_cents": 36000},
        {"name": "保温棉", "quantity": "1套", "amount_cents": 8000},
    ],
    "fee_items": [{"name": "安装服务费", "amount_cents": 28000}],
    "risks": ["室外机支架建议在一年后复检"],
    "after_sales_reminder": "如有异常噪声，请及时联系服务师傅。",
    "total_amount_cents": 0,
    "paid_amount_cents": 20000,
}

AI_REPORT_PAYLOAD = {
    "service_title": "空调控制器更换报告",
    "service_type": "空调维修",
    "work_summary": "控制器更换完成，设备运行正常。",
    "before_status": "原控制器无法启动。",
    "after_status": "通电及保护功能测试通过。",
    "completed_items": [
        {"content": "完成控制器更换和测试", "source": "user_text"}
    ],
    "materials": [
        {
            "name": {"value": "智能控制器", "source": "manual_input"},
            "quantity": {"value": "1台", "source": "manual_input"},
            "amount_cents": {"value": 68000, "source": "manual_input"},
        }
    ],
    "labor": [
        {
            "description": {"value": "安装服务费", "source": "manual_input"},
            "hours": {"value": "2小时", "source": "manual_input"},
            "amount_cents": {"value": 32000, "source": "manual_input"},
        }
    ],
    "risks": [],
    "exceptions": [],
    "customer_confirmation_text": "客户确认设备运行正常。",
    "needs_confirmation": [],
}


@pytest.fixture
def pdf_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalStorage:
    storage = LocalStorage(tmp_path / "pdf-storage", signing_secret="pdf-test-secret")
    monkeypatch.setattr("server.routers.orders.get_storage", lambda: storage)
    return storage


def create_jpeg() -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (800, 520), "#dfeaf4")
    image.save(output, "JPEG", quality=90)
    return output.getvalue()


def prepare_report(client, headers, order_id: str) -> None:
    response = client.put(
        f"/api/v1/service-orders/{order_id}/report",
        headers=headers,
        json=REPORT_PAYLOAD,
    )
    assert response.status_code == 200, response.text


def create_share(client, headers, order_id: str) -> str:
    response = client.post(
        f"/api/v1/service-orders/{order_id}/customer-share",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["share_token"]


def assert_pdf_response(response) -> None:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert "service-order-ORDER-001.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")
    assert b"%%EOF" in response.content[-1024:]
    assert len(response.content) > 10_000


def test_owner_downloads_chinese_pdf_with_photos(
    client,
    auth_headers,
    create_order,
) -> None:
    headers = auth_headers("pdf-owner", technician_name="王师傅")
    order = create_order(headers, status="waiting_acceptance")
    prepare_report(client, headers, order["id"])
    uploaded = client.post(
        f"/api/v1/service-orders/{order['id']}/photos",
        headers=headers,
        data={"phase": "before"},
        files={"file": ("现场照片.jpg", create_jpeg(), "image/jpeg")},
    )
    assert uploaded.status_code == 201, uploaded.text

    response = client.get(
        f"/api/v1/service-orders/{order['id']}/pdf",
        headers=headers,
    )

    assert_pdf_response(response)


def test_pdf_download_is_owner_scoped_and_requires_report(
    client,
    auth_headers,
    create_order,
) -> None:
    owner_headers = auth_headers("pdf-scope-owner")
    stranger_headers = auth_headers("pdf-scope-stranger")
    order = create_order(owner_headers, status="waiting_acceptance")

    missing_report = client.get(
        f"/api/v1/service-orders/{order['id']}/pdf",
        headers=owner_headers,
    )
    hidden = client.get(
        f"/api/v1/service-orders/{order['id']}/pdf",
        headers=stranger_headers,
    )
    anonymous = client.get(f"/api/v1/service-orders/{order['id']}/pdf")

    assert missing_report.status_code == 409
    assert missing_report.json() == {"detail": "服务报告尚未生成"}
    assert hidden.status_code == 404
    assert anonymous.status_code == 401


def test_customer_share_downloads_pdf_without_technician_login(
    client,
    auth_headers,
    create_order,
    pdf_storage: LocalStorage,
) -> None:
    del pdf_storage
    headers = auth_headers("pdf-share-owner")
    order = create_order(headers, status="waiting_acceptance")
    prepare_report(client, headers, order["id"])
    token = create_share(client, headers, order["id"])

    response = client.get(
        f"/api/v1/service-orders/customer-share/{token}/pdf",
    )

    assert_pdf_response(response)
    unsigned_size = len(response.content)

    accepted = client.post(
        f"/api/v1/service-orders/customer-share/{token}/acceptance",
        data={"accepted": "true"},
        files={"signature": ("signature.jpg", create_jpeg(), "image/jpeg")},
    )
    assert accepted.status_code == 201, accepted.text
    signed_pdf = client.get(
        f"/api/v1/service-orders/customer-share/{token}/pdf",
    )
    assert_pdf_response(signed_pdf)
    assert len(signed_pdf.content) != unsigned_size

    tampered = f"{token[:-1]}{'a' if token[-1] != 'a' else 'b'}"
    rejected = client.get(
        f"/api/v1/service-orders/customer-share/{tampered}/pdf",
    )
    assert rejected.status_code == 404


def test_new_ai_report_updates_total_and_exports_pdf(
    client,
    auth_headers,
    create_order,
) -> None:
    headers = auth_headers("pdf-ai-owner")
    order = create_order(headers, status="waiting_acceptance")

    saved = client.put(
        f"/api/v1/service-orders/{order['id']}/ai-report",
        headers=headers,
        json=AI_REPORT_PAYLOAD,
    )
    response = client.get(
        f"/api/v1/service-orders/{order['id']}/pdf",
        headers=headers,
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["total_amount_cents"] == 100000
    assert_pdf_response(response)
