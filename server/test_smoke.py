from uuid import uuid4

from fastapi.testclient import TestClient

from server.main import app


def run() -> None:
    client = TestClient(app)
    order_no = f"TEST-{uuid4().hex[:12]}"
    created = client.post("/api/v1/service-orders", json={
        "order_no": order_no,
        "company_name": "测试服务公司",
        "customer_name": "测试客户",
        "customer_phone": "13800000000",
        "service_address": "测试地址",
        "service_type": "空调安装",
        "technician_name": "测试师傅",
        "status": "in_progress",
    })
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    detail = client.get(f"/api/v1/service-orders/{order_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["order_no"] == order_no

    saved = client.put(f"/api/v1/service-orders/{order_id}/report", json={
        "completed_items": ["已完成测试安装"],
        "materials": [{"name": "铜管", "quantity": "2米", "amount_cents": 16000}],
        "fee_items": [{"name": "安装服务费", "amount_cents": 15000}],
        "risks": [],
        "after_sales_reminder": "12个月后保养",
        "total_amount_cents": 31000,
        "paid_amount_cents": 0,
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["report"]["total_amount_cents"] == 31000
    print(f"smoke test passed: {order_id}")


if __name__ == "__main__":
    run()
