from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ServiceOrder(Base):
    __tablename__ = "service_orders"
    __table_args__ = (
        CheckConstraint("status IN ('draft','in_progress','waiting_acceptance','accepted','cancelled')", name="ck_service_order_status"),
        UniqueConstraint("owner_user_id", "order_no", name="uq_service_orders_owner_order_no"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    order_no: Mapped[str] = mapped_column(String(64), index=True)
    company_name: Mapped[str] = mapped_column(String(200))
    customer_name: Mapped[str] = mapped_column(String(100))
    customer_phone: Mapped[str] = mapped_column(String(50))
    service_address: Mapped[str] = mapped_column(String(500))
    service_type: Mapped[str] = mapped_column(String(300))
    technician_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), index=True, default="draft")
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    paid_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    audio_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    audio_object_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    transcription_status: Mapped[str] = mapped_column(String(32), default="not_started")
    transcription_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    asr_request_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    audio_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    report_generation_status: Mapped[str] = mapped_column(String(32), default="not_started")
    report_generation_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    report_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    photos: Mapped[list["ServiceOrderPhoto"]] = relationship(back_populates="service_order")
    customer_acceptance: Mapped[Optional["CustomerAcceptance"]] = relationship(back_populates="service_order", uselist=False)


class ServiceOrderPhoto(Base):
    __tablename__ = "service_order_photos"
    __table_args__ = (CheckConstraint("phase IN ('before','after')", name="ck_service_order_photo_phase"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    service_order_id: Mapped[str] = mapped_column(ForeignKey("service_orders.id"), index=True)
    phase: Mapped[str] = mapped_column(String(16))
    file_url: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    service_order: Mapped[ServiceOrder] = relationship(back_populates="photos")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    openid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    unionid: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    technician_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="technician")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CustomerAcceptance(Base):
    __tablename__ = "customer_acceptances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    service_order_id: Mapped[str] = mapped_column(ForeignKey("service_orders.id", ondelete="CASCADE"), unique=True, index=True)
    signature_object_key: Mapped[str] = mapped_column(String(512))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    service_order: Mapped[ServiceOrder] = relationship(back_populates="customer_acceptance")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
