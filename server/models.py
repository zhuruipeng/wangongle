from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ServiceOrder(Base):
    __tablename__ = "service_orders"
    __table_args__ = (CheckConstraint("status IN ('draft','in_progress','waiting_acceptance','accepted','cancelled')", name="ck_service_order_status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(200))
    customer_name: Mapped[str] = mapped_column(String(100))
    customer_phone: Mapped[str] = mapped_column(String(50))
    service_address: Mapped[str] = mapped_column(String(500))
    service_type: Mapped[str] = mapped_column(String(300))
    technician_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), index=True, default="draft")
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    paid_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transcription_status: Mapped[str] = mapped_column(String(32), default="not_started")
    transcription_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    asr_request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    audio_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_generation_status: Mapped[str] = mapped_column(String(32), default="not_started")
    report_generation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    report_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    photos: Mapped[list["ServiceOrderPhoto"]] = relationship(back_populates="service_order")
    acceptance_links: Mapped[list["ServiceAcceptanceLink"]] = relationship(back_populates="service_order")
    acceptance: Mapped["ServiceAcceptance | None"] = relationship(back_populates="service_order", uselist=False)


class ServiceOrderPhoto(Base):
    __tablename__ = "service_order_photos"
    __table_args__ = (CheckConstraint("phase IN ('before','after')", name="ck_service_order_photo_phase"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    service_order_id: Mapped[str] = mapped_column(ForeignKey("service_orders.id"), index=True)
    phase: Mapped[str] = mapped_column(String(16))
    file_url: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    service_order: Mapped[ServiceOrder] = relationship(back_populates="photos")


class ServiceAcceptanceLink(Base):
    __tablename__ = "service_acceptance_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    service_order_id: Mapped[str] = mapped_column(ForeignKey("service_orders.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    service_order: Mapped[ServiceOrder] = relationship(back_populates="acceptance_links")


class ServiceAcceptance(Base):
    __tablename__ = "service_acceptances"
    __table_args__ = (UniqueConstraint("service_order_id", name="uq_service_acceptance_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    service_order_id: Mapped[str] = mapped_column(ForeignKey("service_orders.id"), index=True)
    acceptance_version: Mapped[str] = mapped_column(String(32))
    signer_name: Mapped[str] = mapped_column(String(100))
    statement_text: Mapped[str] = mapped_column(Text)
    signature_file_url: Mapped[str] = mapped_column(String(500))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    report_snapshot_json: Mapped[str] = mapped_column(Text)
    photos_snapshot_json: Mapped[str] = mapped_column(Text)
    total_amount_cents: Mapped[int] = mapped_column(Integer)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    service_order: Mapped[ServiceOrder] = relationship(back_populates="acceptance")
