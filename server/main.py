import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, UPLOAD_DIR, engine, get_db
from .migrations import migrate
from .models import ServiceOrder, ServiceOrderPhoto
from .services.report_generator import ReportGenerationError, generate_service_report
from .services.speech_to_text import SpeechToTextError, transcribe_audio
from .settings import get_ai_report_settings, get_asr_settings
from .schemas import (
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

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
AUDIO_TYPES = {
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
    "audio/x-wav": ".wav", "audio/mp4": ".m4a", "audio/aac": ".aac",
    "audio/ogg": ".ogg", "application/octet-stream": ".mp3",
}

Base.metadata.create_all(bind=engine)
migrate(engine)
app = FastAPI(title="干完了本地开发 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("GANWANLE_CORS_ORIGINS", "http://localhost:10086,http://127.0.0.1:10086").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.get("/api/health")
def health():
    return {"status": "ok"}


def get_order_or_404(db: Session, order_id: str) -> ServiceOrder:
    order = db.get(ServiceOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="服务单不存在")
    return order


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


def order_response(order: ServiceOrder) -> ServiceOrderResponse:
    photos = sorted(order.photos, key=lambda item: (item.phase, item.sort_order, item.created_at))
    return ServiceOrderResponse(
        id=order.id, order_no=order.order_no, company_name=order.company_name,
        customer_name=order.customer_name, customer_phone=order.customer_phone,
        service_address=order.service_address, service_type=order.service_type,
        technician_name=order.technician_name, status=order.status,
        transcript=order.transcript, report=report_from_order(order), generated_report=generated_report_from_order(order),
        total_amount_cents=order.total_amount_cents, paid_amount_cents=order.paid_amount_cents,
        audio_url=order.audio_url,
        transcription_status=order.transcription_status,
        transcription_error=order.transcription_error,
        asr_request_id=order.asr_request_id,
        audio_duration_ms=order.audio_duration_ms,
        report_generation_status=order.report_generation_status,
        report_generation_error=order.report_generation_error,
        report_model=order.report_model,
        report_generated_at=order.report_generated_at,
        before_photos=[PhotoResponse.model_validate(item) for item in photos if item.phase == "before"],
        after_photos=[PhotoResponse.model_validate(item) for item in photos if item.phase == "after"],
        created_at=order.created_at, updated_at=order.updated_at,
    )


@app.post("/api/v1/service-orders", response_model=ServiceOrderResponse, status_code=status.HTTP_201_CREATED)
def create_service_order(payload: ServiceOrderCreate, db: Session = Depends(get_db)):
    order = ServiceOrder(**payload.model_dump())
    db.add(order)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="服务单号已存在") from error
    db.refresh(order)
    return order_response(order)


@app.get("/api/v1/service-orders", response_model=list[ServiceOrderResponse])
def list_service_orders(status_filter: Optional[str] = Query(default=None, alias="status"), db: Session = Depends(get_db)):
    statement = select(ServiceOrder).order_by(ServiceOrder.created_at.desc())
    if status_filter:
        allowed = {"draft", "in_progress", "waiting_acceptance", "accepted", "cancelled"}
        if status_filter not in allowed:
            raise HTTPException(status_code=422, detail="无效的服务单状态")
        statement = statement.where(ServiceOrder.status == status_filter)
    return [order_response(order) for order in db.scalars(statement).all()]


@app.get("/api/v1/service-orders/{order_id}", response_model=ServiceOrderResponse)
def get_service_order(order_id: str, db: Session = Depends(get_db)):
    return order_response(get_order_or_404(db, order_id))


@app.patch("/api/v1/service-orders/{order_id}", response_model=ServiceOrderResponse)
def patch_service_order(order_id: str, payload: ServiceOrderPatch, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(order, key, value)
    db.commit(); db.refresh(order)
    return order_response(order)


async def save_upload(file: UploadFile, folder: str, allowed_types: dict[str, str], max_bytes: int) -> tuple[str, str]:
    suffix = allowed_types.get((file.content_type or "").lower())
    original_name = Path(file.filename or "upload").name
    original_suffix = Path(original_name).suffix.lower()
    if not suffix or (original_suffix and original_suffix not in set(allowed_types.values())):
        raise HTTPException(status_code=415, detail="不支持的文件格式")
    target_dir = UPLOAD_DIR / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid4().hex}{suffix}"
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail="上传文件过大")
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return f"/uploads/{folder}/{target.name}", original_name


@app.post("/api/v1/service-orders/{order_id}/photos", response_model=PhotoResponse, status_code=201)
async def upload_photo(order_id: str, phase: Literal["before", "after"] = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id)
    file_url, original_name = await save_upload(file, "photos", IMAGE_TYPES, 10 * 1024 * 1024)
    current_count = len([photo for photo in order.photos if photo.phase == phase])
    photo = ServiceOrderPhoto(service_order_id=order.id, phase=phase, file_url=file_url, original_filename=original_name, sort_order=current_count)
    db.add(photo); db.commit(); db.refresh(photo)
    return photo


@app.delete("/api/v1/service-orders/{order_id}/photos/{photo_id}", status_code=204)
def delete_photo(order_id: str, photo_id: str, db: Session = Depends(get_db)):
    get_order_or_404(db, order_id)
    photo = db.scalar(select(ServiceOrderPhoto).where(ServiceOrderPhoto.id == photo_id, ServiceOrderPhoto.service_order_id == order_id))
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在或不属于当前服务单")
    relative_path = photo.file_url.removeprefix("/uploads/")
    target = (UPLOAD_DIR / relative_path).resolve()
    if UPLOAD_DIR.resolve() in target.parents:
        target.unlink(missing_ok=True)
    db.delete(photo); db.commit()


@app.post("/api/v1/service-orders/{order_id}/audio", response_model=AudioResponse)
async def upload_audio(order_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id)
    file_url, _ = await save_upload(file, "audio", AUDIO_TYPES, 20 * 1024 * 1024)
    order.audio_url = file_url
    order.transcription_status = "not_started"
    order.transcription_error = None
    order.asr_request_id = None
    order.audio_duration_ms = None
    db.commit(); db.refresh(order)
    return AudioResponse(audio_url=file_url)


@app.post("/api/v1/service-orders/{order_id}/transcribe", response_model=TranscriptionResponse)
def transcribe_order_audio(order_id: str, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id)
    if not order.audio_url:
        raise HTTPException(status_code=400, detail="服务单尚未上传录音")
    settings = get_asr_settings()
    if not settings.is_configured:
        raise HTTPException(status_code=503, detail="语音服务尚未配置")
    relative_path = order.audio_url.removeprefix("/uploads/")
    audio_path = (UPLOAD_DIR / relative_path).resolve()
    if UPLOAD_DIR.resolve() not in audio_path.parents:
        raise HTTPException(status_code=400, detail="录音文件路径无效")
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
        db.commit()
        return TranscriptionResponse(status="failed", error=summary)
    order.transcript = result.transcript
    order.transcription_status = "succeeded"
    order.transcription_error = None
    order.asr_request_id = result.request_id
    order.audio_duration_ms = result.audio_duration_ms
    db.commit()
    return TranscriptionResponse(
        status="succeeded",
        transcript=result.transcript,
        audio_duration_ms=result.audio_duration_ms,
    )


@app.post("/api/v1/service-orders/{order_id}/generate-report", response_model=GenerateReportResponse)
def generate_order_report(order_id: str, force: bool = Query(default=False), db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id)
    if not order.transcript or not order.transcript.strip():
        raise HTTPException(status_code=400, detail="请先保存师傅确认后的语音文字")
    if order.report_generation_status == "processing":
        raise HTTPException(status_code=409, detail="服务报告正在整理，请勿重复提交")
    if order.report_json and not force:
        raise HTTPException(status_code=409, detail="服务单已有报告，确认后才能重新生成")
    settings = get_ai_report_settings()
    if not settings.is_configured:
        order.report_generation_status = "failed"
        order.report_generation_error = "AI报告服务尚未配置"
        db.commit()
        raise HTTPException(status_code=503, detail="AI报告服务尚未配置")

    claimed = db.execute(
        update(ServiceOrder)
        .where(
            ServiceOrder.id == order.id,
            ServiceOrder.report_generation_status != "processing",
        )
        .values(
            report_generation_status="processing",
            report_generation_error=None,
            report_model=settings.model,
        )
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="服务报告正在整理，请勿重复提交")
    db.commit()
    db.refresh(order)
    try:
        result = generate_service_report(order.service_type, order.transcript.strip(), settings)
    except ReportGenerationError as error:
        summary = str(error)[:500] or "AI报告生成失败"
        order.report_generation_status = "failed"
        order.report_generation_error = summary
        db.commit()
        raise HTTPException(status_code=502, detail=summary) from None

    order.report_json = result.report.model_dump_json()
    order.total_amount_cents = result.total_amount_cents
    order.report_generation_status = "succeeded"
    order.report_generation_error = None
    order.report_model = settings.model
    order.report_generated_at = datetime.now(timezone.utc)
    db.commit()
    return GenerateReportResponse(
        status="succeeded",
        report=result.report,
        total_amount_cents=result.total_amount_cents,
        paid_amount_cents=order.paid_amount_cents,
        due_amount_cents=max(0, result.total_amount_cents - order.paid_amount_cents),
        model=settings.model,
    )


@app.put("/api/v1/service-orders/{order_id}/report", response_model=ServiceOrderResponse)
def save_report(order_id: str, payload: ReportPayload, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id)
    material_total = sum(item.amount_cents or 0 for item in payload.materials)
    fee_total = sum(item.amount_cents or 0 for item in payload.fee_items)
    recalculated_total = material_total + fee_total
    normalized_payload = payload.model_copy(update={"total_amount_cents": recalculated_total})
    order.report_json = normalized_payload.model_dump_json()
    order.total_amount_cents = recalculated_total
    order.paid_amount_cents = payload.paid_amount_cents
    db.commit(); db.refresh(order)
    return order_response(order)


@app.post("/api/v1/service-orders/{order_id}/submit-acceptance", response_model=ServiceOrderResponse)
def submit_acceptance(order_id: str, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id)
    order.status = "waiting_acceptance"
    db.commit(); db.refresh(order)
    return order_response(order)
