from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OrderStatus = Literal["draft", "in_progress", "waiting_acceptance", "accepted", "cancelled"]


class ServiceOrderCreate(BaseModel):
    order_no: str = Field(min_length=1, max_length=64)
    company_name: str = Field(min_length=1, max_length=200)
    customer_name: str = Field(min_length=1, max_length=100)
    customer_phone: str = Field(min_length=1, max_length=50)
    service_address: str = Field(min_length=1, max_length=500)
    service_type: str = Field(min_length=1, max_length=300)
    technician_name: str = Field(min_length=1, max_length=100)
    status: OrderStatus = "draft"


class ServiceOrderPatch(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    customer_name: str | None = Field(default=None, min_length=1, max_length=100)
    customer_phone: str | None = Field(default=None, min_length=1, max_length=50)
    service_address: str | None = Field(default=None, min_length=1, max_length=500)
    service_type: str | None = Field(default=None, min_length=1, max_length=300)
    technician_name: str | None = Field(default=None, min_length=1, max_length=100)
    status: OrderStatus | None = None
    transcript: str | None = Field(default=None, max_length=10000)


class MaterialItem(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: str = Field(min_length=1, max_length=100)
    amount_cents: int | None = Field(default=None, ge=0)


class FeeItem(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount_cents: int | None = Field(default=None, ge=0)


class ReportPayload(BaseModel):
    completed_items: list[str] = Field(default_factory=list, max_length=100)
    materials: list[MaterialItem] = Field(default_factory=list, max_length=100)
    fee_items: list[FeeItem] = Field(default_factory=list, max_length=100)
    risks: list[str] = Field(default_factory=list, max_length=100)
    after_sales_reminder: str = Field(default="", max_length=5000)
    total_amount_cents: int = Field(ge=0)
    paid_amount_cents: int = Field(ge=0)


class GeneratedCompletedItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(min_length=1, max_length=1000)
    source_text: str = Field(min_length=1, max_length=2000)


class GeneratedMaterialItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    quantity: float | None
    unit: str = Field(max_length=50)
    unit_price_cents: int | None = Field(ge=0)
    amount_cents: int | None = Field(ge=0)
    source_text: str = Field(min_length=1, max_length=2000)
    needs_confirmation: Literal[True]

    @model_validator(mode="after")
    def prevent_unpriced_amount(self):
        if self.unit_price_cents is None and self.amount_cents is not None:
            raise ValueError("unit price is null so amount must be null")
        return self


class GeneratedLaborItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    amount_cents: int | None = Field(ge=0)
    source_text: str = Field(min_length=1, max_length=2000)
    needs_confirmation: Literal[True]


class GeneratedTextItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(min_length=1, max_length=1000)
    source_text: str = Field(min_length=1, max_length=2000)


class GeneratedServiceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(max_length=2000)
    completed_items: list[GeneratedCompletedItem] = Field(max_length=100)
    materials: list[GeneratedMaterialItem] = Field(max_length=100)
    labor_items: list[GeneratedLaborItem] = Field(max_length=100)
    risks: list[GeneratedTextItem] = Field(max_length=100)
    after_sales: list[GeneratedTextItem] = Field(max_length=100)
    missing_information: list[str] = Field(max_length=100)
    warnings: list[str] = Field(max_length=100)


class GenerateReportResponse(BaseModel):
    status: Literal["succeeded"]
    report: GeneratedServiceReport
    total_amount_cents: int
    paid_amount_cents: int
    due_amount_cents: int
    model: str


class PhotoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    phase: Literal["before", "after"]
    file_url: str
    original_filename: str
    sort_order: int
    created_at: datetime


class ServiceOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    order_no: str
    company_name: str
    customer_name: str
    customer_phone: str
    service_address: str
    service_type: str
    technician_name: str
    status: OrderStatus
    transcript: str | None
    report: ReportPayload | None
    generated_report: GeneratedServiceReport | None
    total_amount_cents: int
    paid_amount_cents: int
    audio_url: str | None
    transcription_status: Literal["not_started", "processing", "succeeded", "failed"]
    transcription_error: str | None
    asr_request_id: str | None
    audio_duration_ms: int | None
    report_generation_status: Literal["not_started", "processing", "succeeded", "failed"]
    report_generation_error: str | None
    report_model: str | None
    report_generated_at: datetime | None
    before_photos: list[PhotoResponse]
    after_photos: list[PhotoResponse]
    created_at: datetime
    updated_at: datetime


class AudioResponse(BaseModel):
    audio_url: str


class TranscriptionResponse(BaseModel):
    status: Literal["succeeded", "failed"]
    transcript: str | None = None
    audio_duration_ms: int | None = None
    error: str | None = None
