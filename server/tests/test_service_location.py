def test_service_order_persists_precise_map_location(
    client,
    auth_headers,
    create_order,
) -> None:
    headers = auth_headers("location-owner")
    order = create_order(
        headers,
        status="waiting_acceptance",
        service_address="山东省临沂市兰山区金雀山路 88 号 测试大厦",
        service_location_name="测试大厦",
        service_latitude=35.052345,
        service_longitude=118.347891,
    )

    assert order["service_location_name"] == "测试大厦"
    assert order["service_latitude"] == 35.052345
    assert order["service_longitude"] == 118.347891

    share = client.post(
        f"/api/v1/service-orders/{order['id']}/customer-share",
        headers=headers,
    )
    shared = client.get(
        f"/api/v1/service-orders/customer-share/{share.json()['share_token']}",
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["service_latitude"] == 35.052345
    assert shared.json()["service_longitude"] == 118.347891


def test_service_order_rejects_incomplete_or_invalid_coordinates(
    client,
    auth_headers,
) -> None:
    headers = auth_headers("location-validation-owner")
    base_payload = {
        "order_no": "LOCATION-INVALID-1",
        "company_name": "测试服务公司",
        "customer_name": "测试客户",
        "customer_phone": "13800000000",
        "service_address": "测试地址",
        "service_type": "设备检修",
        "status": "in_progress",
    }

    incomplete = client.post(
        "/api/v1/service-orders",
        headers=headers,
        json={**base_payload, "service_latitude": 35.0},
    )
    out_of_range = client.post(
        "/api/v1/service-orders",
        headers=headers,
        json={
            **base_payload,
            "order_no": "LOCATION-INVALID-2",
            "service_latitude": 95.0,
            "service_longitude": 118.0,
        },
    )

    assert incomplete.status_code == 422
    assert out_of_range.status_code == 422


def test_service_order_patch_rejects_incomplete_coordinates(
    client,
    auth_headers,
    create_order,
) -> None:
    headers = auth_headers("location-patch-validation-owner")
    order = create_order(headers)

    response = client.patch(
        f"/api/v1/service-orders/{order['id']}",
        headers=headers,
        json={"service_latitude": 35.0},
    )

    assert response.status_code == 422
