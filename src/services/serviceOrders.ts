import { apiRequest, downloadFile, publicApiRequest, publicDownloadFile, publicUploadFile, uploadFile } from './api'

export type OrderStatus = 'draft' | 'in_progress' | 'waiting_acceptance' | 'accepted' | 'cancelled'
export type ApiPhoto = { id: string; phase: 'before' | 'after'; file_url: string; original_filename: string; sort_order: number; created_at: string }
export type ApiReport = {
  completed_items: string[]
  materials: Array<{ name: string; quantity: string; amount_cents: number | null }>
  fee_items: Array<{ name: string; amount_cents: number | null }>
  risks: string[]
  after_sales_reminder: string
  total_amount_cents: number
  paid_amount_cents: number
}
export type ApiGeneratedReport = {
  summary: string
  completed_items: Array<{ content: string; source_text: string }>
  materials: Array<{ name: string; quantity: number | null; unit: string; unit_price_cents: number | null; amount_cents: number | null; source_text: string; needs_confirmation: boolean }>
  labor_items: Array<{ name: string; amount_cents: number | null; source_text: string; needs_confirmation: boolean }>
  risks: Array<{ content: string; source_text: string }>
  after_sales: Array<{ content: string; source_text: string }>
  missing_information: string[]
  warnings: string[]
}
export type GenerateReportResult = { status: 'succeeded'; report: ApiGeneratedReport; total_amount_cents: number; paid_amount_cents: number; due_amount_cents: number; model: string }
export type AiReportSource = 'user_text' | 'manual_input' | 'unknown'
export type ApiAiReportSourceValue = { value: string | null; source: AiReportSource }
export type ApiAiReportMoneyValue = { value: number | null; source: AiReportSource }
export type ApiAiServiceReportDraft = {
  service_title: string | null
  service_type: string
  work_summary: string | null
  before_status: string | null
  after_status: string | null
  completed_items: Array<{ content: string; source: AiReportSource }>
  materials: Array<{ name: ApiAiReportSourceValue; quantity: ApiAiReportSourceValue; amount_cents: ApiAiReportMoneyValue }>
  labor: Array<{ description: ApiAiReportSourceValue; hours: ApiAiReportSourceValue; amount_cents: ApiAiReportMoneyValue }>
  risks: string[]
  exceptions: string[]
  customer_confirmation_text: string | null
  needs_confirmation: string[]
}
export type GenerateAiReportResult = { status: 'succeeded'; report: ApiAiServiceReportDraft; model: string }
export type ApiAcceptance = {
  status: 'accepted'
  acceptance: { id: string; accepted_at: string; signature_url: string }
}
export type ApiServiceOrder = {
  id: string; order_no: string; company_name: string; customer_name: string; customer_phone: string
  service_address: string; service_location_name: string | null; service_latitude: number | null; service_longitude: number | null
  service_type: string; technician_name: string; status: OrderStatus
  transcript: string | null; report: ApiReport | null; generated_report: ApiGeneratedReport | null; total_amount_cents: number; paid_amount_cents: number
  ai_report: ApiAiServiceReportDraft | null
  audio_url: string | null; before_photos: ApiPhoto[]; after_photos: ApiPhoto[]; created_at: string; updated_at: string
  transcription_status: 'not_started' | 'processing' | 'succeeded' | 'failed'
  transcription_error: string | null; asr_request_id: string | null; audio_duration_ms: number | null
  report_generation_status: 'not_started' | 'processing' | 'succeeded' | 'failed'
  report_generation_error: string | null; report_model: string | null; report_generated_at: string | null
}
export type ApiCustomerSharedOrder = {
  id: string; order_no: string; company_name: string; customer_name: string
  service_address: string; service_location_name: string | null; service_latitude: number | null; service_longitude: number | null
  service_type: string; technician_name: string
  status: 'waiting_acceptance' | 'accepted'
  report: ApiReport | null; ai_report: ApiAiServiceReportDraft | null
  total_amount_cents: number; paid_amount_cents: number
  before_photos: ApiPhoto[]; after_photos: ApiPhoto[]
}
export type ApiCustomerShare = { share_token: string; expires_in: number }
export type CreateOrderPayload = {
  order_no: string; company_name: string; customer_name: string; customer_phone: string
  service_address: string; service_location_name?: string; service_latitude?: number; service_longitude?: number
  service_type: string; status: OrderStatus
}

export const createServiceOrder = (payload: CreateOrderPayload) => apiRequest<ApiServiceOrder>('/api/v1/service-orders', { method: 'POST', data: payload })
export const listServiceOrders = (status?: OrderStatus) => apiRequest<ApiServiceOrder[]>(`/api/v1/service-orders${status ? `?status=${status}` : ''}`)
export const getServiceOrder = (id: string) => apiRequest<ApiServiceOrder>(`/api/v1/service-orders/${id}`)
export const patchServiceOrder = (id: string, data: { status?: OrderStatus; transcript?: string }) => apiRequest<ApiServiceOrder>(`/api/v1/service-orders/${id}`, { method: 'PATCH', data })
export const uploadOrderPhoto = (id: string, phase: 'before' | 'after', filePath: string) => uploadFile<ApiPhoto>(`/api/v1/service-orders/${id}/photos`, filePath, { phase })
export const deleteOrderPhoto = (id: string, photoId: string) => apiRequest<void>(`/api/v1/service-orders/${id}/photos/${photoId}`, { method: 'DELETE' })
export const uploadOrderAudio = (id: string, filePath: string) => uploadFile<{ audio_url: string }>(`/api/v1/service-orders/${id}/audio`, filePath)
export const transcribeOrderAudio = (id: string) => apiRequest<{ status: 'succeeded' | 'failed'; transcript?: string; audio_duration_ms?: number; error?: string }>(`/api/v1/service-orders/${id}/transcribe`, { method: 'POST', timeout: 45000 })
export const generateOrderReport = (id: string, force = false) => apiRequest<GenerateReportResult>(`/api/v1/service-orders/${id}/generate-report?force=${force}`, { method: 'POST', timeout: 120000 })
export const generateAiOrderReport = (id: string, manualText = '', force = false) => apiRequest<GenerateAiReportResult>(`/api/v1/service-orders/${id}/ai-report?force=${force}`, { method: 'POST', data: { manual_text: manualText }, timeout: 120000 })
export const saveOrderReport = (id: string, report: ApiReport) => apiRequest<ApiServiceOrder>(`/api/v1/service-orders/${id}/report`, { method: 'PUT', data: report })
export const saveAiOrderReport = (id: string, report: ApiAiServiceReportDraft) => apiRequest<ApiServiceOrder>(`/api/v1/service-orders/${id}/ai-report`, { method: 'PUT', data: report })
export const submitOrderAcceptance = (id: string) => apiRequest<ApiServiceOrder>(`/api/v1/service-orders/${id}/submit-acceptance`, { method: 'POST' })
export const acceptServiceOrder = (id: string, signaturePath: string) =>
  uploadFile<ApiAcceptance>(`/api/v1/service-orders/${id}/acceptance`, signaturePath, { accepted: 'true' }, 'signature')
export const createCustomerShare = (id: string) =>
  apiRequest<ApiCustomerShare>(`/api/v1/service-orders/${id}/customer-share`, { method: 'POST' })
export const getCustomerSharedOrder = (shareToken: string) =>
  publicApiRequest<ApiCustomerSharedOrder>(`/api/v1/service-orders/customer-share/${encodeURIComponent(shareToken)}`)
export const downloadOrderPdf = (id: string) =>
  downloadFile(`/api/v1/service-orders/${id}/pdf`)
export const downloadCustomerSharedOrderPdf = (shareToken: string) =>
  publicDownloadFile(`/api/v1/service-orders/customer-share/${encodeURIComponent(shareToken)}/pdf`)
export const acceptCustomerSharedOrder = (shareToken: string, signaturePath: string) =>
  publicUploadFile<ApiAcceptance>(
    `/api/v1/service-orders/customer-share/${encodeURIComponent(shareToken)}/acceptance`,
    signaturePath,
    { accepted: 'true' },
    'signature'
  )
