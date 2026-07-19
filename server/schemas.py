from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OrderStatus = Literal["draft", "in_progress", "waiting_acceptance", "accepted", "cancelled"]
MutableOrderStatus = Literal["draft", "in_progress", "waiting_acceptance", "cancelled"]


class ServiceOrderCreate(BaseModel):
    order_no: str = Field(min_length=1, max_length=64)
    company_name: str = Field(min_length=1, max_length=200)
    customer_name: str = Field(min_length=1, max_length=100)
    customer_phone: str = Field(min_length=1, max_length=50)
    service_address: str = Field(min_length=1, max_length=500)
    service_type: str = Field(min_length=1, max_length=300)
    status: MutableOrderStatus = "draft"


class ServiceOrderPatch(BaseModel):
    company_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    customer_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    customer_phone: Optional[str] = Field(default=None, min_length=1, max_length=50)
    service_address: Optional[str] = Field(default=None, min_length=1, max_length=500)
    service_type: Optional[str] = Field(default=None, min_length=1, max_length=300)
    status: Optional[MutableOrderStatus] = None
    transcript: Optional[str] = Field(default=None, max_length=10000)


class MaterialItem(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: str = Field(min_length=1, max_length=100)
    amount_cents: Optional[int] = Field(default=None, ge=0)


class FeeItem(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount_cents: Optional[int] = Field(default=None, ge=0)


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
    quantity: Optional[float]
    unit: str = Field(max_length=50)
    unit_price_cents: Optional[int] = Field(ge=0)
    amount_cents: Optional[int] = Field(ge=0)
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
    amount_cents: Optional[int] = Field(ge=0)
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


AiReportSource = Literal["user_text", "manual_input", "unknown"]


class AiReportSourceValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: Optional[str] = Field(default=None, max_length=2000)
    source: AiReportSource

    @model_validator(mode="after")
    def unknown_source_must_be_null(self):
        if self.source == "unknown" and self.value is not None:
            raise ValueError("unknown source values must be null")
        if self.source != "unknown" and self.value is not None and not self.value.strip():
            raise ValueError("sourced values must not be blank")
        return self


class AiReportMoneyValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: Optional[int] = Field(default=None, ge=0)
    source: AiReportSource

    @model_validator(mode="after")
    def unknown_source_must_be_null(self):
        if self.source == "unknown" and self.value is not None:
            raise ValueError("unknown source amounts must be null")
        return self


class AiReportCompletedItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(min_length=1, max_length=1000)
    source: AiReportSource


class AiReportMaterialItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: AiReportSourceValue
    quantity: AiReportSourceValue
    amount_cents: AiReportMoneyValue


class AiReportLaborItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    description: AiReportSourceValue
    hours: AiReportSourceValue
    amount_cents: AiReportMoneyValue


class AiServiceReportDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    service_title: Optional[str] = Field(default=None, max_length=200)
    service_type: str = Field(min_length=1, max_length=300)
    work_summary: Optional[str] = Field(default=None, max_length=2000)
    before_status: Optional[str] = Field(default=None, max_length=2000)
    after_status: Optional[str] = Field(default=None, max_length=2000)
    completed_items: list[AiReportCompletedItem] = Field(default_factory=list, max_length=100)
    materials: list[AiReportMaterialItem] = Field(default_factory=list, max_length=100)
    labor: list[AiReportLaborItem] = Field(default_factory=list, max_length=100)
    risks: list[str] = Field(default_factory=list, max_length=100)
    exceptions: list[str] = Field(default_factory=list, max_length=100)
    customer_confirmation_text: Optional[str] = Field(default=None, max_length=2000)
    needs_confirmation: list[str] = Field(default_factory=list, max_length=100)


class AiReportGenerateRequest(BaseModel):
    service_type: Optional[str] = Field(default=None, min_length=1, max_length=300)
    manual_text: Optional[str] = Field(default=None, max_length=10000)

    @field_validator("manual_text", mode="before")
    @classmethod
    def trim_manual_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip()


class AiReportGenerateResponse(BaseModel):
    status: Literal["succeeded"]
    report: AiServiceReportDraft
    model: str


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
    content_type: str
    size_bytes: int
    sha256: str
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
    transcript: Optional[str]
    report: Optional[ReportPayload]
    generated_report: Optional[GeneratedServiceReport]
    ai_report: Optional[AiServiceReportDraft]
    total_amount_cents: int
    paid_amount_cents: int
    audio_url: Optional[str]
    transcription_status: Literal["not_started", "processing", "succeeded", "failed"]
    transcription_error: Optional[str]
    asr_request_id: Optional[str]
    audio_duration_ms: Optional[int]
    report_generation_status: Literal["not_started", "processing", "succeeded", "failed"]
    report_generation_error: Optional[str]
    report_model: Optional[str]
    report_generated_at: Optional[datetime]
    before_photos: list[PhotoResponse]
    after_photos: list[PhotoResponse]
    created_at: datetime
    updated_at: datetime


class CustomerShareResponse(BaseModel):
    share_token: str
    expires_in: int


class CustomerSharedOrderResponse(BaseModel):
    id: str
    order_no: str
    company_name: str
    customer_name: str
    service_address: str
    service_type: str
    technician_name: str
    status: Literal["waiting_acceptance", "accepted"]
    report: Optional[ReportPayload]
    ai_report: Optional[AiServiceReportDraft]
    total_amount_cents: int
    paid_amount_cents: int
    before_photos: list[PhotoResponse]
    after_photos: list[PhotoResponse]


class AudioResponse(BaseModel):
    audio_url: str


class TranscriptionResponse(BaseModel):
    status: Literal["succeeded", "failed"]
    transcript: Optional[str] = None
    audio_duration_ms: Optional[int] = None
    error: Optional[str] = None


class AcceptanceMetadata(BaseModel):
    id: str
    accepted_at: datetime
    signature_url: str


class AcceptanceResponse(BaseModel):
    status: Literal["accepted"]
    acceptance: AcceptanceMetadata


class WeChatLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=512)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class ProfileUpdateRequest(BaseModel):
    technician_name: str = Field(min_length=1, max_length=100)

    @field_validator("technician_name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("technician_name must not be blank")
        return value


class AuthUserResponse(BaseModel):
    id: str
    role: str
    technician_name: Optional[str]
    profile_complete: bool


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: AuthUserResponse


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
