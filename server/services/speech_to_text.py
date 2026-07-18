from pathlib import Path

from ..settings import AsrSettings
from .tencent_asr import TencentAsrResult, recognize_sentence

MAX_TENCENT_AUDIO_BYTES = 3 * 1024 * 1024


class SpeechToTextError(Exception):
    pass


def transcribe_audio(audio_path: Path, settings: AsrSettings) -> TencentAsrResult:
    if not settings.is_configured:
        raise SpeechToTextError("语音服务尚未配置")
    if not audio_path.is_file():
        raise SpeechToTextError("录音文件不存在")
    if audio_path.suffix.lower() != ".mp3":
        raise SpeechToTextError("当前仅支持 MP3 录音识别")
    if audio_path.stat().st_size > MAX_TENCENT_AUDIO_BYTES:
        raise SpeechToTextError("录音文件超过语音识别大小限制")
    try:
        result = recognize_sentence(audio_path, settings)
    except SpeechToTextError:
        raise
    except Exception as error:
        # Do not expose SDK request data, signatures, credentials, or tracebacks.
        raise SpeechToTextError("腾讯云语音识别调用失败") from error
    if not result.transcript:
        raise SpeechToTextError("未识别到有效语音内容")
    return result
