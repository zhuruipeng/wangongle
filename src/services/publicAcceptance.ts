import Taro from '@tarojs/taro'
import { API_BASE_URL } from './api'

export type PublicPhoto = { phase: 'before' | 'after'; file_url: string; sort_order: number }
export type PublicMaterial = { name: string; quantity: string; amount_cents: number | null }
export type PublicFee = { name: string; amount_cents: number | null }
export type PublicAcceptanceData = {
  company_name: string
  order_no: string
  customer_name: string
  service_type: string
  service_address: string
  technician_name: string
  completed_at: string
  before_photos: PublicPhoto[]
  after_photos: PublicPhoto[]
  completed_items: string[]
  materials: PublicMaterial[]
  fee_items: PublicFee[]
  total_amount_cents: number
  paid_amount_cents: number
  due_amount_cents: number
  risks: string[]
  after_sales_reminder: string
  acceptance_statement: string
  status: 'waiting_acceptance' | 'accepted'
  accepted_at: string | null
}

export class PublicAcceptanceError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function getPublicAcceptance(token: string): Promise<PublicAcceptanceData> {
  try {
    const response = await Taro.request<PublicAcceptanceData | { detail?: string }>({
      url: `${API_BASE_URL}/api/v1/public/acceptance`,
      method: 'GET',
      header: { Authorization: `Bearer ${token}` },
      timeout: 15000
    })
    if (response.statusCode < 200 || response.statusCode >= 300) {
      const body = response.data as { detail?: string }
      throw new PublicAcceptanceError(body.detail || '验收页面加载失败', response.statusCode)
    }
    return response.data as PublicAcceptanceData
  } catch (error) {
    if (error instanceof PublicAcceptanceError) throw error
    throw new PublicAcceptanceError(error instanceof Error ? error.message : '网络连接失败', 0)
  }
}

export async function confirmPublicAcceptance(
  token: string,
  signerName: string,
  signatureSource: string
): Promise<PublicAcceptanceData> {
  if (Taro.getEnv() === Taro.ENV_TYPE.WEB) {
    const formData = new FormData()
    formData.append('signer_name', signerName)
    formData.append('acceptance_statement_version', '1')
    formData.append('confirmed', 'true')
    formData.append('signature', dataUrlToPng(signatureSource), 'signature.png')
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/public/acceptance/confirm`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
        cache: 'no-store'
      })
      const body = await response.json() as PublicAcceptanceData | { detail?: string }
      if (!response.ok) throw new PublicAcceptanceError((body as { detail?: string }).detail || '确认验收失败', response.status)
      return body as PublicAcceptanceData
    } catch (error) {
      if (error instanceof PublicAcceptanceError) throw error
      throw new PublicAcceptanceError(error instanceof Error ? error.message : '网络连接失败', 0)
    }
  }

  try {
    const response = await Taro.uploadFile({
      url: `${API_BASE_URL}/api/v1/public/acceptance/confirm`,
      filePath: signatureSource,
      name: 'signature',
      header: { Authorization: `Bearer ${token}` },
      formData: {
        signer_name: signerName,
        acceptance_statement_version: '1',
        confirmed: 'true'
      },
      timeout: 30000
    })
    const body = response.data ? JSON.parse(response.data) : {}
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw new PublicAcceptanceError(body.detail || '确认验收失败', response.statusCode)
    }
    return body as PublicAcceptanceData
  } catch (error) {
    if (error instanceof PublicAcceptanceError) throw error
    throw new PublicAcceptanceError(error instanceof Error ? error.message : '网络连接失败', 0)
  }
}

function dataUrlToPng(dataUrl: string): Blob {
  const match = /^data:image\/png;base64,(.+)$/.exec(dataUrl)
  if (!match) throw new PublicAcceptanceError('签名导出失败，请重新签名', 0)
  const binary = atob(match[1])
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return new Blob([bytes], { type: 'image/png' })
}
