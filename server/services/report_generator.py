import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from pydantic import ValidationError

from ..schemas import GeneratedServiceReport
from ..settings import AiReportSettings
from .qwen_report_generator import request_qwen_report


class ReportGenerationError(Exception):
    pass


@dataclass(frozen=True)
class GeneratedReportResult:
    report: GeneratedServiceReport
    total_amount_cents: int


def _validate_source_text(report: GeneratedServiceReport, transcript: str) -> None:
    normalized_transcript = "".join(transcript.split())
    sourced_items = [
        *report.completed_items,
        *report.materials,
        *report.labor_items,
        *report.risks,
        *report.after_sales,
    ]
    if any("".join(item.source_text.split()) not in normalized_transcript for item in sourced_items):
        raise ReportGenerationError("报告内容缺少可核对的原始语音依据")


def validate_and_recalculate(raw_json: str, transcript: str) -> GeneratedReportResult:
    try:
        payload = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as error:
        raise ReportGenerationError("模型未返回有效JSON") from error
    try:
        report = GeneratedServiceReport.model_validate(payload)
    except ValidationError as error:
        raise ReportGenerationError("模型报告结构不符合要求") from error

    _validate_source_text(report, transcript)

    material_total = 0
    for material in report.materials:
        if material.unit_price_cents is None or material.quantity is None:
            material.amount_cents = None
            continue
        calculated = (Decimal(str(material.quantity)) * Decimal(material.unit_price_cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        material.amount_cents = int(calculated)
        material_total += material.amount_cents
    labor_total = sum(item.amount_cents or 0 for item in report.labor_items)
    return GeneratedReportResult(report=report, total_amount_cents=material_total + labor_total)


def generate_service_report(service_type: str, transcript: str, settings: AiReportSettings) -> GeneratedReportResult:
    if not settings.is_configured:
        raise ReportGenerationError("AI报告服务尚未配置")
    last_error: ReportGenerationError | None = None
    for _ in range(2):
        try:
            return validate_and_recalculate(request_qwen_report(service_type, transcript, settings), transcript)
        except ReportGenerationError as error:
            last_error = error
        except Exception as error:
            last_error = ReportGenerationError("阿里云百炼调用失败")
            last_error.__cause__ = error
    raise last_error or ReportGenerationError("AI报告生成失败")
