import { apiRequest, uploadFile } from './api'

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
export type ApiServiceOrder = {
  id: string; order_no: string; company_name: string; customer_name: string; customer_phone: string
  service_address: string; service_type: string; technician_name: string; status: OrderStatus
  transcript: string | null; report: ApiReport | null; generated_report: ApiGeneratedReport | null; total_amount_cents: number; paid_amount_cents: number
  audio_url: string | null; before_photos: ApiPhoto[]; after_photos: ApiPhoto[]; created_at: string; updated_at: string
  transcription_status: 'not_started' | 'processing' | 'succeeded' | 'failed'
  transcription_error: string | null; asr_request_id: string | null; audio_duration_ms: number | null
  report_generation_status: 'not_started' | 'processing' | 'succeeded' | 'failed'
  report_generation_error: string | null; report_model: string | null; report_generated_at: string | null
}
export type CreateOrderPayload = {
  order_no: string; company_name: string; customer_name: string; customer_phone: string
  service_address: string; service_type: string; status: OrderStatus
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
export const saveOrderReport = (id: string, report: ApiReport) => apiRequest<ApiServiceOrder>(`/api/v1/service-orders/${id}/report`, { method: 'PUT', data: report })
export const submitOrderAcceptance = (id: string) => apiRequest<ApiServiceOrder>(`/api/v1/service-orders/${id}/submit-acceptance`, { method: 'POST' })
