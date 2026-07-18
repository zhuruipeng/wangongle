import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, UPLOAD_DIR, engine, get_db
from .migrations import migrate
from .models import ServiceAcceptance, ServiceAcceptanceLink, ServiceOrder, ServiceOrderPhoto
from .services.acceptance import (
    ACCEPTANCE_STATEMENT,
    ACCEPTANCE_VERSION,
    build_photos_snapshot,
    build_report_snapshot,
    build_snapshot_hash,
    canonical_json,
    create_acceptance_token,
    ensure_utc,
    file_sha256,
    hash_acceptance_token,
    utc_now,
)
from .services.report_generator import ReportGenerationError, generate_service_report
from .services.speech_to_text import SpeechToTextError, transcribe_audio
from .settings import get_acceptance_settings, get_ai_report_settings, get_asr_settings
from .schemas import (
    AcceptanceLinkResponse,
    AcceptanceLinkRevokeResponse,
    AudioResponse,
    FeeItem,
    GenerateReportResponse,
    GeneratedServiceReport,
    MaterialItem,
    PhotoResponse,
    PublicAcceptancePhoto,
    PublicAcceptanceResponse,
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

try:
    Base.metadata.create_all(bind=engine)
    migrate(engine)
except Exception as error:
    raise RuntimeError(f"数据库迁移失败：{error}") from error
app = FastAPI(title="干完了本地开发 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("GANWANLE_CORS_ORIGINS", "http://localhost:10086,http://127.0.0.1:10086").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
bearer_scheme = HTTPBearer(auto_error=False)


@app.middleware("http")
async def disable_public_acceptance_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/public/acceptance"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    return {"status": "ok"}


def get_order_or_404(db: Session, order_id: str) -> ServiceOrder:
    order = db.get(ServiceOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="服务单不存在")
    return order


def ensure_order_unlocked(order: ServiceOrder) -> None:
    if order.status == "accepted":
        raise HTTPException(status_code=409, detail="该服务单已验收，内容已锁定")


def report_from_order(order: ServiceOrder) -> ReportPayload | None:
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


def generated_report_from_order(order: ServiceOrder) -> GeneratedServiceReport | None:
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
        accepted_at=order.accepted_at,
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
def list_service_orders(status_filter: str | None = Query(default=None, alias="status"), db: Session = Depends(get_db)):
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
    ensure_order_unlocked(order)
    if payload.status == "accepted":
        raise HTTPException(status_code=409, detail="服务单只能通过客户验收接口变为已验收")
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
    ensure_order_unlocked(order)
    file_url, original_name = await save_upload(file, "photos", IMAGE_TYPES, 10 * 1024 * 1024)
    current_count = len([photo for photo in order.photos if photo.phase == phase])
    photo = ServiceOrderPhoto(service_order_id=order.id, phase=phase, file_url=file_url, original_filename=original_name, sort_order=current_count)
    db.add(photo); db.commit(); db.refresh(photo)
    return photo


@app.delete("/api/v1/service-orders/{order_id}/photos/{photo_id}", status_code=204)
def delete_photo(order_id: str, photo_id: str, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id)
    ensure_order_unlocked(order)
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
    ensure_order_unlocked(order)
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
    ensure_order_unlocked(order)
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
    ensure_order_unlocked(order)
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
    ensure_order_unlocked(order)
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
    ensure_order_unlocked(order)
    order.status = "waiting_acceptance"
    db.commit(); db.refresh(order)
    return order_response(order)


def get_public_acceptance_link(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> ServiceAcceptanceLink:
    if not credentials or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=401, detail="验收链接无效")
    token = credentials.credentials
    if len(token) > 500:
        raise HTTPException(status_code=401, detail="验收链接无效")
    link = db.scalar(select(ServiceAcceptanceLink).where(
        ServiceAcceptanceLink.token_hash == hash_acceptance_token(token)
    ))
    if not link:
        raise HTTPException(status_code=401, detail="验收链接无效")
    now = utc_now()
    if link.revoked_at is not None:
        raise HTTPException(status_code=410, detail="验收链接已撤销")
    if ensure_utc(link.expires_at) <= now:
        raise HTTPException(status_code=410, detail="验收链接已过期")
    return link


def public_acceptance_response(
    order: ServiceOrder,
    *,
    acceptance: ServiceAcceptance | None = None,
) -> PublicAcceptanceResponse:
    acceptance = acceptance or order.acceptance
    if acceptance:
        report_snapshot = json.loads(acceptance.report_snapshot_json)
        photos_snapshot = json.loads(acceptance.photos_snapshot_json)
        accepted_at = acceptance.accepted_at
        public_status = "accepted"
    else:
        report = report_from_order(order)
        if not report:
            raise HTTPException(status_code=409, detail="服务报告尚未保存")
        report_snapshot = build_report_snapshot(order, report)
        photos_snapshot = [
            {"phase": photo.phase, "file_url": photo.file_url, "sort_order": photo.sort_order}
            for photo in sorted(order.photos, key=lambda item: (item.phase, item.sort_order, item.created_at))
        ]
        accepted_at = None
        public_status = "waiting_acceptance"

    before_photos = [PublicAcceptancePhoto.model_validate(item) for item in photos_snapshot if item["phase"] == "before"]
    after_photos = [PublicAcceptancePhoto.model_validate(item) for item in photos_snapshot if item["phase"] == "after"]
    return PublicAcceptanceResponse(
        company_name=report_snapshot["company_name"],
        order_no=report_snapshot["order_no"],
        customer_name=report_snapshot["customer_name"],
        service_type=report_snapshot["service_type"],
        service_address=report_snapshot["service_address"],
        technician_name=report_snapshot["technician_name"],
        completed_at=report_snapshot["completed_at"],
        before_photos=before_photos,
        after_photos=after_photos,
        completed_items=report_snapshot["completed_items"],
        materials=report_snapshot["materials"],
        fee_items=report_snapshot["fee_items"],
        total_amount_cents=report_snapshot["total_amount_cents"],
        paid_amount_cents=report_snapshot["paid_amount_cents"],
        due_amount_cents=report_snapshot["due_amount_cents"],
        risks=report_snapshot["risks"],
        after_sales_reminder=report_snapshot["after_sales_reminder"],
        acceptance_statement=ACCEPTANCE_STATEMENT,
        status=public_status,
        accepted_at=accepted_at,
    )


@app.post("/api/v1/service-orders/{order_id}/acceptance-link", response_model=AcceptanceLinkResponse)
def create_acceptance_link(order_id: str, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id)
    ensure_order_unlocked(order)
    if not report_from_order(order):
        raise HTTPException(status_code=409, detail="请先保存最终服务报告")

    settings = get_acceptance_settings()
    now = utc_now()
    db.execute(
        update(ServiceAcceptanceLink)
        .where(
            ServiceAcceptanceLink.service_order_id == order.id,
            ServiceAcceptanceLink.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    raw_token, token_hash = create_acceptance_token()
    expires_at = now + timedelta(days=settings.expires_days)
    db.add(ServiceAcceptanceLink(
        service_order_id=order.id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))
    order.status = "waiting_acceptance"
    db.commit()
    separator = "&" if "?" in settings.public_h5_base_url else "?"
    public_url = f"{settings.public_h5_base_url}{separator}{urlencode({'token': raw_token})}"
    return AcceptanceLinkResponse(url=public_url, expires_at=expires_at)


@app.post(
    "/api/v1/service-orders/{order_id}/acceptance-link/revoke",
    response_model=AcceptanceLinkRevokeResponse,
)
def revoke_acceptance_link(order_id: str, db: Session = Depends(get_db)):
    get_order_or_404(db, order_id)
    now = utc_now()
    db.execute(
        update(ServiceAcceptanceLink)
        .where(
            ServiceAcceptanceLink.service_order_id == order_id,
            ServiceAcceptanceLink.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    db.commit()
    return AcceptanceLinkRevokeResponse(status="revoked")


@app.get("/api/v1/public/acceptance", response_model=PublicAcceptanceResponse)
def get_public_acceptance(
    link: ServiceAcceptanceLink = Depends(get_public_acceptance_link),
    db: Session = Depends(get_db),
):
    order = get_order_or_404(db, link.service_order_id)
    link.last_accessed_at = utc_now()
    response = public_acceptance_response(order)
    db.commit()
    return response


@app.post("/api/v1/public/acceptance/confirm", response_model=PublicAcceptanceResponse)
async def confirm_public_acceptance(
    signer_name: str = Form(...),
    acceptance_statement_version: str = Form(...),
    confirmed: bool = Form(...),
    signature: UploadFile = File(...),
    link: ServiceAcceptanceLink = Depends(get_public_acceptance_link),
    db: Session = Depends(get_db),
):
    order = get_order_or_404(db, link.service_order_id)
    existing = db.scalar(select(ServiceAcceptance).where(ServiceAcceptance.service_order_id == order.id))
    if existing or order.status == "accepted":
        raise HTTPException(status_code=409, detail="该服务单已经验收")
    if order.status != "waiting_acceptance":
        raise HTTPException(status_code=409, detail="该服务单当前不能验收")
    if not confirmed:
        raise HTTPException(status_code=422, detail="请先勾选客户验收声明")
    if acceptance_statement_version != ACCEPTANCE_VERSION:
        raise HTTPException(status_code=422, detail="验收声明版本无效，请刷新页面后重试")
    clean_signer_name = signer_name.strip()
    if not clean_signer_name or len(clean_signer_name) > 100:
        raise HTTPException(status_code=422, detail="请填写正确的客户姓名")
    if (signature.content_type or "").lower() != "image/png":
        raise HTTPException(status_code=415, detail="签名只接受PNG格式")

    signature_bytes = await signature.read(2 * 1024 * 1024 + 1)
    await signature.close()
    if len(signature_bytes) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="签名图片不能超过2MB")
    if len(signature_bytes) <= 8 or not signature_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=422, detail="请提供有效的手写签名PNG")

    report = report_from_order(order)
    if not report:
        raise HTTPException(status_code=409, detail="服务报告尚未保存")
    try:
        report_snapshot = build_report_snapshot(order, report)
        photos_snapshot = build_photos_snapshot(order.photos)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None

    accepted_at = utc_now()
    signature_dir = UPLOAD_DIR / "signatures"
    signature_dir.mkdir(parents=True, exist_ok=True)
    signature_path = signature_dir / f"{uuid4().hex}.png"
    signature_path.write_bytes(signature_bytes)
    signature_url = f"/uploads/signatures/{signature_path.name}"
    snapshot_hash = build_snapshot_hash(
        report_snapshot,
        photos_snapshot,
        signer_name=clean_signer_name,
        statement_text=ACCEPTANCE_STATEMENT,
        acceptance_version=ACCEPTANCE_VERSION,
        accepted_at=accepted_at,
        signature_sha256=file_sha256(signature_path),
    )
    acceptance = ServiceAcceptance(
        service_order_id=order.id,
        acceptance_version=ACCEPTANCE_VERSION,
        signer_name=clean_signer_name,
        statement_text=ACCEPTANCE_STATEMENT,
        signature_file_url=signature_url,
        accepted_at=accepted_at,
        report_snapshot_json=canonical_json(report_snapshot),
        photos_snapshot_json=canonical_json(photos_snapshot),
        total_amount_cents=order.total_amount_cents,
        snapshot_hash=snapshot_hash,
    )
    db.add(acceptance)
    order.status = "accepted"
    order.accepted_at = accepted_at
    link.last_accessed_at = accepted_at
    link.used_at = accepted_at
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        signature_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="该服务单已经验收") from None
    except Exception:
        db.rollback()
        signature_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="验收保存失败，请稍后重试") from None
    return public_acceptance_response(order, acceptance=acceptance)
