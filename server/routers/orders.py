from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditEvent, ServiceOrder, ServiceOrderPhoto, User
from ..schemas import (
    AudioResponse,
    FeeItem,
    GenerateReportResponse,
    GeneratedServiceReport,
    MaterialItem,
    PhotoResponse,
    ReportPayload,
    ServiceOrderCreate,
    ServiceOrderPatch,
    ServiceOrderResponse,
    TranscriptionResponse,
)
from ..security import get_current_user
from ..services.report_generator import ReportGenerationError, generate_service_report
from ..services.speech_to_text import SpeechToTextError, transcribe_audio
from ..settings import get_ai_report_settings, get_asr_settings, get_storage_settings
from ..storage import LocalStorage, StorageBackend, build_object_key, get_storage

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
AUDIO_TYPES = {
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
    "audio/x-wav": ".wav", "audio/mp4": ".m4a", "audio/aac": ".aac",
    "audio/ogg": ".ogg", "application/octet-stream": ".mp3",
}

router = APIRouter(tags=["service-orders"])
REPORT_CLAIM_LEASE = timedelta(minutes=5)


def get_order_or_404(db: Session, user_id: str, order_id: str) -> ServiceOrder:
    order = db.scalar(
        select(ServiceOrder).where(
            ServiceOrder.id == order_id,
            ServiceOrder.owner_user_id == user_id,
        )
    )
    if order is None:
        raise HTTPException(status_code=404, detail="服务单不存在")
    return order


def add_audit(
    db: Session,
    request: Request,
    user: User,
    order_id: str,
    event_type: str,
    outcome: str,
) -> None:
    db.add(AuditEvent(
        user_id=user.id,
        resource_type="service_order",
        resource_id=order_id,
        request_id=request.state.request_id,
        event_type=event_type,
        outcome=outcome,
    ))


def mark_report_claim_failed(
    db: Session,
    request: Request,
    user: User,
    order_id: str,
    claim_time: datetime,
    summary: str,
) -> None:
    db.rollback()
    failed = db.execute(
        update(ServiceOrder)
        .where(
            ServiceOrder.id == order_id,
            ServiceOrder.owner_user_id == user.id,
            ServiceOrder.report_generation_status == "processing",
            ServiceOrder.updated_at == claim_time,
        )
        .values(
            report_generation_status="failed",
            report_generation_error=summary,
            updated_at=datetime.now(timezone.utc),
        )
    )
    if failed.rowcount != 1:
        db.rollback()
        return
    db.commit()
    try:
        add_audit(db, request, user, order_id, "report_generation", "failed")
        db.commit()
    except Exception:
        db.rollback()


def report_from_order(order: ServiceOrder) -> Optional[ReportPayload]:
    if not order.report_json:
        return None
    try:
        return ReportPayload.model_validate_json(order.report_json)
    except ValueError:
        generated = GeneratedServiceReport.model_validate_json(order.report_json)
        return ReportPayload(
            completed_items=[item.content for item in generated.completed_items],
            materials=[MaterialItem(
                name=item.name,
                quantity=f"{item.quantity:g}{item.unit}" if item.quantity is not None else item.unit,
                amount_cents=item.amount_cents,
            ) for item in generated.materials],
            fee_items=[FeeItem(name=item.name, amount_cents=item.amount_cents) for item in generated.labor_items],
            risks=[item.content for item in generated.risks],
            after_sales_reminder="；".join(item.content for item in generated.after_sales),
            total_amount_cents=order.total_amount_cents,
            paid_amount_cents=order.paid_amount_cents,
        )


def generated_report_from_order(order: ServiceOrder) -> Optional[GeneratedServiceReport]:
    if not order.report_json:
        return None
    try:
        return GeneratedServiceReport.model_validate_json(order.report_json)
    except ValueError:
        return None


def photo_response(photo: ServiceOrderPhoto, storage: StorageBackend) -> PhotoResponse:
    if not photo.object_key:
        raise RuntimeError("photo is missing its private object key")
    return PhotoResponse(
        id=photo.id,
        phase=photo.phase,
        file_url=storage.presigned_get_url(photo.object_key, get_storage_settings().presigned_seconds),
        original_filename=photo.original_filename,
        content_type=photo.content_type or "application/octet-stream",
        size_bytes=photo.size_bytes or 0,
        sha256=photo.sha256 or "",
        sort_order=photo.sort_order,
        created_at=photo.created_at,
    )


def order_response(order: ServiceOrder) -> ServiceOrderResponse:
    storage = get_storage()
    photos = sorted(order.photos, key=lambda item: (item.phase, item.sort_order, item.created_at))
    return ServiceOrderResponse(
        id=order.id, order_no=order.order_no, company_name=order.company_name,
        customer_name=order.customer_name, customer_phone=order.customer_phone,
        service_address=order.service_address, service_type=order.service_type,
        technician_name=order.technician_name, status=order.status,
        transcript=order.transcript, report=report_from_order(order), generated_report=generated_report_from_order(order),
        total_amount_cents=order.total_amount_cents, paid_amount_cents=order.paid_amount_cents,
        audio_url=(
            storage.presigned_get_url(order.audio_object_key, get_storage_settings().presigned_seconds)
            if order.audio_object_key else None
        ),
        transcription_status=order.transcription_status,
        transcription_error=order.transcription_error,
        asr_request_id=order.asr_request_id,
        audio_duration_ms=order.audio_duration_ms,
        report_generation_status=order.report_generation_status,
        report_generation_error=order.report_generation_error,
        report_model=order.report_model,
        report_generated_at=order.report_generated_at,
        before_photos=[photo_response(item, storage) for item in photos if item.phase == "before"],
        after_photos=[photo_response(item, storage) for item in photos if item.phase == "after"],
        created_at=order.created_at, updated_at=order.updated_at,
    )


def object_key_owner(key: str) -> Optional[str]:
    parts = key.split("/")
    try:
        users_index = parts.index("users")
        return parts[users_index + 1]
    except (ValueError, IndexError):
        return None


@router.get("/private-files/{key:path}", include_in_schema=False)
def get_private_local_file(
    key: str,
    expires: int = Query(...),
    signature: str = Query(..., min_length=64, max_length=64),
    current_user: User = Depends(get_current_user),
):
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise HTTPException(status_code=404, detail="文件不存在")
    if object_key_owner(key) != current_user.id:
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        path = storage.validate_presigned_get(key, expires, signature)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="文件不存在") from None
    except ValueError:
        raise HTTPException(status_code=403, detail="文件签名无效或已过期") from None
    return FileResponse(path)


@router.post("", response_model=ServiceOrderResponse, status_code=status.HTTP_201_CREATED)
def create_service_order(
    payload: ServiceOrderCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    technician_name = (current_user.technician_name or "").strip()
    if not technician_name:
        raise HTTPException(status_code=403, detail="请先完善师傅资料")
    order = ServiceOrder(
        **payload.model_dump(),
        owner_user_id=current_user.id,
        technician_name=technician_name,
    )
    try:
        db.add(order)
        db.flush()
        add_audit(db, request, current_user, order.id, "order_created", "succeeded")
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="服务单号已存在") from error
    db.refresh(order)
    return order_response(order)


@router.get("", response_model=list[ServiceOrderResponse])
def list_service_orders(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = (
        select(ServiceOrder)
        .where(ServiceOrder.owner_user_id == current_user.id)
        .order_by(ServiceOrder.created_at.desc())
    )
    if status_filter:
        allowed = {"draft", "in_progress", "waiting_acceptance", "accepted", "cancelled"}
        if status_filter not in allowed:
            raise HTTPException(status_code=422, detail="无效的服务单状态")
        statement = statement.where(ServiceOrder.status == status_filter)
    return [order_response(order) for order in db.scalars(statement).all()]


@router.get("/{order_id}", response_model=ServiceOrderResponse)
def get_service_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return order_response(get_order_or_404(db, current_user.id, order_id))


@router.patch("/{order_id}", response_model=ServiceOrderResponse)
def patch_service_order(
    order_id: str,
    payload: ServiceOrderPatch,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = get_order_or_404(db, current_user.id, order_id)
    previous_status = order.status
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(order, key, value)
    if payload.status == "accepted" and previous_status != "accepted":
        add_audit(db, request, current_user, order.id, "acceptance", "succeeded")
    db.commit()
    db.refresh(order)
    return order_response(order)


@dataclass(frozen=True)
class ValidatedUpload:
    stream: BytesIO
    original_name: str
    content_type: str
    suffix: str
    size_bytes: int
    sha256: str


async def read_validated_upload(
    file: UploadFile,
    allowed_types: dict[str, str],
    max_bytes: int,
) -> ValidatedUpload:
    content_type = (file.content_type or "").lower()
    suffix = allowed_types.get(content_type)
    original_name = Path(file.filename or "upload").name
    original_suffix = Path(original_name).suffix.lower()
    if not suffix or (original_suffix and original_suffix not in set(allowed_types.values())):
        raise HTTPException(status_code=415, detail="不支持的文件格式")
    buffer = BytesIO()
    digest = sha256()
    size = 0
    try:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(status_code=413, detail="上传文件过大")
            digest.update(chunk)
            buffer.write(chunk)
    finally:
        await file.close()
    buffer.seek(0)
    return ValidatedUpload(buffer, original_name, content_type, suffix, size, digest.hexdigest())


@router.post("/{order_id}/photos", response_model=PhotoResponse, status_code=201)
async def upload_photo(
    order_id: str,
    request: Request,
    phase: Literal["before", "after"] = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = get_order_or_404(db, current_user.id, order_id)
    upload = await read_validated_upload(file, IMAGE_TYPES, 10 * 1024 * 1024)
    storage = get_storage()
    storage_settings = get_storage_settings()
    object_key = build_object_key(
        storage_settings.environment, current_user.id, order.id, "photos", upload.suffix
    )
    storage.put(object_key, upload.stream, upload.content_type)
    current_count = len([photo for photo in order.photos if photo.phase == phase])
    photo = ServiceOrderPhoto(
        service_order_id=order.id,
        phase=phase,
        file_url="",
        original_filename=upload.original_name,
        object_key=object_key,
        content_type=upload.content_type,
        size_bytes=upload.size_bytes,
        sha256=upload.sha256,
        sort_order=current_count,
    )
    try:
        db.add(photo)
        add_audit(db, request, current_user, order.id, "photo_uploaded", "succeeded")
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(object_key)
        raise
    db.refresh(photo)
    return photo_response(photo, storage)


@router.delete("/{order_id}/photos/{photo_id}", status_code=204)
def delete_photo(
    order_id: str,
    photo_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = get_order_or_404(db, current_user.id, order_id)
    photo = db.scalar(
        select(ServiceOrderPhoto).where(
            ServiceOrderPhoto.id == photo_id,
            ServiceOrderPhoto.service_order_id == order.id,
        )
    )
    if photo is None:
        raise HTTPException(status_code=404, detail="照片不存在或不属于当前服务单")
    object_key = photo.object_key
    try:
        db.delete(photo)
        add_audit(db, request, current_user, order.id, "photo_deleted", "succeeded")
        db.commit()
    except Exception:
        db.rollback()
        raise
    if object_key:
        try:
            get_storage().delete(object_key)
        except Exception:
            pass


@router.post("/{order_id}/audio", response_model=AudioResponse)
async def upload_audio(
    order_id: str,
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = get_order_or_404(db, current_user.id, order_id)
    upload = await read_validated_upload(file, AUDIO_TYPES, 20 * 1024 * 1024)
    storage = get_storage()
    storage_settings = get_storage_settings()
    object_key = build_object_key(
        storage_settings.environment, current_user.id, order.id, "audio-pending", upload.suffix
    )
    storage.put(object_key, upload.stream, upload.content_type)
    old_object_key = order.audio_object_key
    order.audio_url = ""
    order.audio_object_key = object_key
    order.transcription_status = "not_started"
    order.transcription_error = None
    order.asr_request_id = None
    order.audio_duration_ms = None
    try:
        add_audit(db, request, current_user, order.id, "audio_uploaded", "succeeded")
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(object_key)
        raise
    db.refresh(order)
    if old_object_key and old_object_key != object_key:
        try:
            storage.delete(old_object_key)
        except Exception:
            pass
    return AudioResponse(
        audio_url=storage.presigned_get_url(object_key, storage_settings.presigned_seconds)
    )


@router.post("/{order_id}/transcribe", response_model=TranscriptionResponse)
def transcribe_order_audio(
    order_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = get_order_or_404(db, current_user.id, order_id)
    if not order.audio_object_key:
        add_audit(db, request, current_user, order.id, "transcription", "failed")
        db.commit()
        raise HTTPException(status_code=400, detail="服务单尚未上传录音")
    settings = get_asr_settings()
    if not settings.is_configured:
        add_audit(db, request, current_user, order.id, "transcription", "failed")
        db.commit()
        raise HTTPException(status_code=503, detail="语音服务尚未配置")
    with TemporaryDirectory(prefix="ganwanle-asr-") as temporary_directory:
        suffix = Path(order.audio_object_key).suffix
        audio_path = Path(temporary_directory) / f"audio{suffix}"
        get_storage().download_to(order.audio_object_key, audio_path)
        order.transcription_status = "processing"
        order.transcription_error = None
        db.commit()
        try:
            result = transcribe_audio(audio_path, settings)
        except SpeechToTextError as error:
            summary = str(error)[:500] or "语音识别失败"
            order.transcription_status = "failed"
            order.transcription_error = summary
            order.asr_request_id = None
            order.audio_duration_ms = None
            add_audit(db, request, current_user, order.id, "transcription", "failed")
            db.commit()
            return TranscriptionResponse(status="failed", error=summary)
    order.transcript = result.transcript
    order.transcription_status = "succeeded"
    order.transcription_error = None
    order.asr_request_id = result.request_id
    order.audio_duration_ms = result.audio_duration_ms
    add_audit(db, request, current_user, order.id, "transcription", "succeeded")
    db.commit()
    return TranscriptionResponse(
        status="succeeded",
        transcript=result.transcript,
        audio_duration_ms=result.audio_duration_ms,
    )


@router.post("/{order_id}/generate-report", response_model=GenerateReportResponse)
def generate_order_report(
    order_id: str,
    request: Request,
    force: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = get_order_or_404(db, current_user.id, order_id)
    if not order.transcript or not order.transcript.strip():
        add_audit(db, request, current_user, order.id, "report_generation", "failed")
        db.commit()
        raise HTTPException(status_code=400, detail="请先保存师傅确认后的语音文字")
    if order.report_json and not force:
        add_audit(db, request, current_user, order.id, "report_generation", "failed")
        db.commit()
        raise HTTPException(status_code=409, detail="服务单已有报告，确认后才能重新生成")
    settings = get_ai_report_settings()
    if not settings.is_configured:
        order.report_generation_status = "failed"
        order.report_generation_error = "AI报告服务尚未配置"
        add_audit(db, request, current_user, order.id, "report_generation", "failed")
        db.commit()
        raise HTTPException(status_code=503, detail="AI报告服务尚未配置")

    claim_time = datetime.now(timezone.utc)
    try:
        claimed = db.execute(
            update(ServiceOrder)
            .where(
                ServiceOrder.id == order.id,
                ServiceOrder.owner_user_id == current_user.id,
                or_(
                    ServiceOrder.report_generation_status != "processing",
                    ServiceOrder.updated_at < claim_time - REPORT_CLAIM_LEASE,
                ),
            )
            .values(
                report_generation_status="processing",
                report_generation_error=None,
                report_model=settings.model,
                updated_at=claim_time,
            )
        )
        db.commit()
    except Exception:
        mark_report_claim_failed(
            db, request, current_user, order.id, claim_time, "服务报告生成失败"
        )
        raise
    if claimed.rowcount != 1:
        add_audit(db, request, current_user, order.id, "report_generation", "failed")
        db.commit()
        raise HTTPException(status_code=409, detail="服务报告正在整理，请勿重复提交")
    db.refresh(order)
    try:
        result = generate_service_report(order.service_type, order.transcript.strip(), settings)
    except ReportGenerationError as error:
        summary = str(error)[:500] or "AI报告生成失败"
        mark_report_claim_failed(db, request, current_user, order.id, claim_time, summary)
        raise HTTPException(status_code=502, detail=summary) from None
    except Exception:
        mark_report_claim_failed(
            db, request, current_user, order.id, claim_time, "服务报告生成失败"
        )
        raise

    try:
        completed = db.execute(
            update(ServiceOrder)
            .where(
                ServiceOrder.id == order.id,
                ServiceOrder.owner_user_id == current_user.id,
                ServiceOrder.report_generation_status == "processing",
                ServiceOrder.updated_at == claim_time,
            )
            .values(
                report_json=result.report.model_dump_json(),
                total_amount_cents=result.total_amount_cents,
                report_generation_status="succeeded",
                report_generation_error=None,
                report_model=settings.model,
                report_generated_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        if completed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="服务报告生成任务已被新的请求接管")
        add_audit(db, request, current_user, order.id, "report_generation", "succeeded")
        db.commit()
        db.refresh(order)
    except HTTPException:
        raise
    except Exception:
        mark_report_claim_failed(
            db, request, current_user, order.id, claim_time, "服务报告生成失败"
        )
        raise
    return GenerateReportResponse(
        status="succeeded",
        report=result.report,
        total_amount_cents=result.total_amount_cents,
        paid_amount_cents=order.paid_amount_cents,
        due_amount_cents=max(0, result.total_amount_cents - order.paid_amount_cents),
        model=settings.model,
    )


@router.put("/{order_id}/report", response_model=ServiceOrderResponse)
def save_report(
    order_id: str,
    payload: ReportPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = get_order_or_404(db, current_user.id, order_id)
    material_total = sum(item.amount_cents or 0 for item in payload.materials)
    fee_total = sum(item.amount_cents or 0 for item in payload.fee_items)
    recalculated_total = material_total + fee_total
    normalized_payload = payload.model_copy(update={"total_amount_cents": recalculated_total})
    order.report_json = normalized_payload.model_dump_json()
    order.total_amount_cents = recalculated_total
    order.paid_amount_cents = payload.paid_amount_cents
    db.commit()
    db.refresh(order)
    return order_response(order)


@router.post("/{order_id}/submit-acceptance", response_model=ServiceOrderResponse)
def submit_acceptance(
    order_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = get_order_or_404(db, current_user.id, order_id)
    order.status = "waiting_acceptance"
    add_audit(db, request, current_user, order.id, "acceptance_submitted", "succeeded")
    db.commit()
    db.refresh(order)
    return order_response(order)
