import json
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI
from pydantic import ValidationError

from ..prompts.ai_report_prompt import SYSTEM_PROMPT, build_user_prompt
from ..schemas import AiServiceReportDraft
from ..settings import AiReportSettings
from .report_generator import ReportGenerationError


@dataclass(frozen=True)
class AiReportGenerationResult:
    report: AiServiceReportDraft


def request_ai_report_json(
    service_type: str,
    before_photo_urls: list[str],
    after_photo_urls: list[str],
    transcript: str,
    manual_text: str,
    settings: AiReportSettings,
) -> str:
    client = OpenAI(api_key=settings.api_key, base_url=settings.base_url, timeout=settings.timeout_seconds)
    completion = client.chat.completions.create(
        model=settings.model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_prompt(
                    service_type=service_type,
                    before_photo_urls=before_photo_urls,
                    after_photo_urls=after_photo_urls,
                    transcript=transcript,
                    manual_text=manual_text,
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        extra_body={"enable_thinking": False},
    )
    return completion.choices[0].message.content or ""


def validate_ai_report(raw_json: str) -> AiReportGenerationResult:
    try:
        payload = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as error:
        raise ReportGenerationError("模型未返回有效JSON") from error
    try:
        report = AiServiceReportDraft.model_validate(payload)
    except ValidationError as error:
        raise ReportGenerationError("AI报告结构不符合要求") from error
    return AiReportGenerationResult(report=report)


def generate_ai_service_report(
    *,
    service_type: str,
    before_photo_urls: list[str],
    after_photo_urls: list[str],
    transcript: str,
    manual_text: str,
    settings: AiReportSettings,
) -> AiReportGenerationResult:
    if not settings.is_configured:
        raise ReportGenerationError("AI报告服务尚未配置")
    last_error: Optional[ReportGenerationError] = None
    for _ in range(2):
        try:
            return validate_ai_report(
                request_ai_report_json(
                    service_type=service_type,
                    before_photo_urls=before_photo_urls,
                    after_photo_urls=after_photo_urls,
                    transcript=transcript,
                    manual_text=manual_text,
                    settings=settings,
                )
            )
        except ReportGenerationError as error:
            last_error = error
        except Exception as error:
            last_error = ReportGenerationError("阿里云百炼调用失败")
            last_error.__cause__ = error
    raise last_error or ReportGenerationError("AI报告生成失败")
