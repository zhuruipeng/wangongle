import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..database import UPLOAD_DIR
from ..models import ServiceOrder, ServiceOrderPhoto
from ..schemas import ReportPayload


ACCEPTANCE_VERSION = "1"
ACCEPTANCE_STATEMENT = "我已查看本次服务内容、施工前后照片、使用材料及费用，并确认本次服务已经完成。"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def create_acceptance_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_acceptance_token(token)


def hash_acceptance_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def upload_path_from_url(file_url: str) -> Path:
    relative_path = file_url.removeprefix("/uploads/")
    target = (UPLOAD_DIR / relative_path).resolve()
    if UPLOAD_DIR.resolve() not in target.parents:
        raise ValueError("上传文件路径无效")
    return target


def build_report_snapshot(order: ServiceOrder, report: ReportPayload) -> dict[str, Any]:
    completed_at = ensure_utc(order.updated_at)
    return {
        "company_name": order.company_name,
        "order_no": order.order_no,
        "customer_name": order.customer_name,
        "service_type": order.service_type,
        "service_address": order.service_address,
        "technician_name": order.technician_name,
        "completed_at": completed_at.isoformat(),
        "completed_items": report.completed_items,
        "materials": [item.model_dump(mode="json") for item in report.materials],
        "fee_items": [item.model_dump(mode="json") for item in report.fee_items],
        "total_amount_cents": order.total_amount_cents,
        "paid_amount_cents": order.paid_amount_cents,
        "due_amount_cents": max(0, order.total_amount_cents - order.paid_amount_cents),
        "risks": report.risks,
        "after_sales_reminder": report.after_sales_reminder,
    }


def build_photos_snapshot(photos: list[ServiceOrderPhoto]) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for photo in sorted(photos, key=lambda item: (item.phase, item.sort_order, item.created_at)):
        path = upload_path_from_url(photo.file_url)
        if not path.is_file():
            raise FileNotFoundError("施工照片文件缺失")
        snapshot.append({
            "phase": photo.phase,
            "file_url": photo.file_url,
            "sort_order": photo.sort_order,
            "file_sha256": file_sha256(path),
        })
    return snapshot


def build_snapshot_hash(
    report_snapshot: dict[str, Any],
    photos_snapshot: list[dict[str, Any]],
    *,
    signer_name: str,
    statement_text: str,
    acceptance_version: str,
    accepted_at: datetime,
    signature_sha256: str,
) -> str:
    envelope = {
        "acceptance_version": acceptance_version,
        "accepted_at": ensure_utc(accepted_at).isoformat(),
        "photos": photos_snapshot,
        "report": report_snapshot,
        "signature_sha256": signature_sha256,
        "signer_name": signer_name,
        "statement_text": statement_text,
    }
    return hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()
