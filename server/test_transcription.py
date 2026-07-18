from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from server.services.speech_to_text import SpeechToTextError
from server.services.tencent_asr import TencentAsrResult
from server.settings import AsrSettings
from server.tests.helpers import build_test_client


CONFIGURED = AsrSettings(True, "mock-id", "mock-key", "ap-shanghai", "16k_zh", "空调|10")
UNCONFIGURED = AsrSettings(True, "", "", "ap-shanghai", "16k_zh", "空调|10")


def auth_headers(client: TestClient) -> dict[str, str]:
    with patch(
        "server.routers.auth.exchange_code",
        return_value={"openid": f"transcription-{uuid4().hex}", "unionid": None},
    ), patch("server.routers.auth.check_rate_limit", return_value=True):
        auth = client.post("/api/v1/auth/wechat", json={"code": "transcription-code"})
    assert auth.status_code == 200, auth.text
    headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}
    profile = client.patch(
        "/api/v1/auth/me/profile",
        headers=headers,
        json={"technician_name": "测试师傅"},
    )
    assert profile.status_code == 200, profile.text
    return headers


def create_order(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/api/v1/service-orders", headers=headers, json={
        "order_no": f"ASR-{uuid4().hex[:12]}", "company_name": "测试公司",
        "customer_name": "测试客户", "customer_phone": "13800000000",
        "service_address": "测试地址", "service_type": "空调安装", "status": "in_progress",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload_audio(client: TestClient, order_id: str, headers: dict[str, str]) -> None:
    response = client.post(
        f"/api/v1/service-orders/{order_id}/audio",
        headers=headers,
        files={"file": ("voice.mp3", b"ID3-mocked-audio", "audio/mpeg")},
    )
    assert response.status_code == 200, response.text


def run() -> None:
    client = build_test_client()
    headers = auth_headers(client)
    # 1. Audio exists: mocked Tencent response is persisted.
    success_id = create_order(client, headers); upload_audio(client, success_id, headers)
    with patch("server.routers.orders.get_asr_settings", return_value=CONFIGURED), patch(
        "server.routers.orders.transcribe_audio",
        return_value=TencentAsrResult("完成空调安装，抽真空后试机正常。", "mock-request-id", 12500),
    ):
        response = client.post(f"/api/v1/service-orders/{success_id}/transcribe", headers=headers)
    assert response.status_code == 200 and response.json()["status"] == "succeeded", response.text
    detail = client.get(f"/api/v1/service-orders/{success_id}", headers=headers).json()
    assert detail["transcript"] == "完成空调安装，抽真空后试机正常。"
    assert detail["asr_request_id"] == "mock-request-id" and detail["audio_duration_ms"] == 12500

    # 2. Missing audio is rejected without calling Tencent.
    no_audio_id = create_order(client, headers)
    response = client.post(f"/api/v1/service-orders/{no_audio_id}/transcribe", headers=headers)
    assert response.status_code == 400 and response.json()["detail"] == "服务单尚未上传录音"

    # 3. Tencent failure is converted to a safe summary and failed state.
    failure_id = create_order(client, headers); upload_audio(client, failure_id, headers)
    with patch("server.routers.orders.get_asr_settings", return_value=CONFIGURED), patch(
        "server.routers.orders.transcribe_audio", side_effect=SpeechToTextError("腾讯云语音识别调用失败")
    ):
        response = client.post(f"/api/v1/service-orders/{failure_id}/transcribe", headers=headers)
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    detail = client.get(f"/api/v1/service-orders/{failure_id}", headers=headers).json()
    assert detail["transcription_status"] == "failed"
    assert detail["transcription_error"] == "腾讯云语音识别调用失败"

    # 4. Missing credentials leaves the server healthy and returns a clear response.
    unconfigured_id = create_order(client, headers); upload_audio(client, unconfigured_id, headers)
    with patch("server.routers.orders.get_asr_settings", return_value=UNCONFIGURED):
        response = client.post(f"/api/v1/service-orders/{unconfigured_id}/transcribe", headers=headers)
    assert response.status_code == 503 and response.json()["detail"] == "语音服务尚未配置"
    assert client.get("/api/health").status_code == 200
    print("transcription tests passed: success, missing audio, Tencent failure, unconfigured")


def test_transcription_workflow() -> None:
    run()


if __name__ == "__main__":
    run()
