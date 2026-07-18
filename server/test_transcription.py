from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from server.main import app
from server.services.speech_to_text import SpeechToTextError
from server.services.tencent_asr import TencentAsrResult
from server.settings import AsrSettings

client = TestClient(app)
CONFIGURED = AsrSettings(True, "mock-id", "mock-key", "ap-shanghai", "16k_zh", "空调|10")
UNCONFIGURED = AsrSettings(True, "", "", "ap-shanghai", "16k_zh", "空调|10")


def create_order() -> str:
    response = client.post("/api/v1/service-orders", json={
        "order_no": f"ASR-{uuid4().hex[:12]}", "company_name": "测试公司",
        "customer_name": "测试客户", "customer_phone": "13800000000",
        "service_address": "测试地址", "service_type": "空调安装",
        "technician_name": "测试师傅", "status": "in_progress",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload_audio(order_id: str) -> None:
    response = client.post(
        f"/api/v1/service-orders/{order_id}/audio",
        files={"file": ("voice.mp3", b"ID3-mocked-audio", "audio/mpeg")},
    )
    assert response.status_code == 200, response.text


def run() -> None:
    # 1. Audio exists: mocked Tencent response is persisted.
    success_id = create_order(); upload_audio(success_id)
    with patch("server.main.get_asr_settings", return_value=CONFIGURED), patch(
        "server.main.transcribe_audio",
        return_value=TencentAsrResult("完成空调安装，抽真空后试机正常。", "mock-request-id", 12500),
    ):
        response = client.post(f"/api/v1/service-orders/{success_id}/transcribe")
    assert response.status_code == 200 and response.json()["status"] == "succeeded", response.text
    detail = client.get(f"/api/v1/service-orders/{success_id}").json()
    assert detail["transcript"] == "完成空调安装，抽真空后试机正常。"
    assert detail["asr_request_id"] == "mock-request-id" and detail["audio_duration_ms"] == 12500

    # 2. Missing audio is rejected without calling Tencent.
    no_audio_id = create_order()
    response = client.post(f"/api/v1/service-orders/{no_audio_id}/transcribe")
    assert response.status_code == 400 and response.json()["detail"] == "服务单尚未上传录音"

    # 3. Tencent failure is converted to a safe summary and failed state.
    failure_id = create_order(); upload_audio(failure_id)
    with patch("server.main.get_asr_settings", return_value=CONFIGURED), patch(
        "server.main.transcribe_audio", side_effect=SpeechToTextError("腾讯云语音识别调用失败")
    ):
        response = client.post(f"/api/v1/service-orders/{failure_id}/transcribe")
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    detail = client.get(f"/api/v1/service-orders/{failure_id}").json()
    assert detail["transcription_status"] == "failed"
    assert detail["transcription_error"] == "腾讯云语音识别调用失败"

    # 4. Missing credentials leaves the server healthy and returns a clear response.
    unconfigured_id = create_order(); upload_audio(unconfigured_id)
    with patch("server.main.get_asr_settings", return_value=UNCONFIGURED):
        response = client.post(f"/api/v1/service-orders/{unconfigured_id}/transcribe")
    assert response.status_code == 503 and response.json()["detail"] == "语音服务尚未配置"
    assert client.get("/api/health").status_code == 200
    print("transcription tests passed: success, missing audio, Tencent failure, unconfigured")


if __name__ == "__main__":
    run()
