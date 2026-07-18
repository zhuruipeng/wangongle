import base64
import json
from dataclasses import dataclass
from pathlib import Path

from tencentcloud.asr.v20190614 import asr_client, models
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile

from ..settings import AsrSettings


@dataclass(frozen=True)
class TencentAsrResult:
    transcript: str
    request_id: str
    audio_duration_ms: int


def recognize_sentence(audio_path: Path, settings: AsrSettings) -> TencentAsrResult:
    audio_bytes = audio_path.read_bytes()
    encoded = base64.b64encode(audio_bytes).decode("ascii")
    credentials = credential.Credential(settings.secret_id, settings.secret_key)
    http_profile = HttpProfile()
    http_profile.reqTimeout = settings.timeout_seconds
    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile
    client = asr_client.AsrClient(credentials, settings.region, client_profile)
    request = models.SentenceRecognitionRequest()
    request.from_json_string(json.dumps({
        "EngSerViceType": settings.engine,
        "SourceType": 1,
        "VoiceFormat": "mp3",
        "Data": encoded,
        "DataLen": len(audio_bytes),
        "ConvertNumMode": 1,
        "FilterPunc": 0,
        "HotwordList": settings.hotwords,
    }, ensure_ascii=False))
    response = client.SentenceRecognition(request)
    return TencentAsrResult(
        transcript=(response.Result or "").strip(),
        request_id=response.RequestId or "",
        audio_duration_ms=int(response.AudioDuration or 0),
    )
