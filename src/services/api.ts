import Taro from '@tarojs/taro'

declare const __GANWANLE_API_BASE_URL__: string

// Replaced by Taro/Webpack at build time. Mini Program runtime has no Node.js `process` global.
export const API_BASE_URL = __GANWANLE_API_BASE_URL__.replace(/\/$/, '')

type RequestOptions = { method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'; data?: unknown; timeout?: number }

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    const response = await Taro.request<T>({
      url: `${API_BASE_URL}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header: { 'content-type': 'application/json' },
      timeout: options.timeout || 15000
    })
    if (response.statusCode < 200 || response.statusCode >= 300) {
      const body = response.data as { detail?: string }
      throw new Error(body?.detail || `请求失败（${response.statusCode}）`)
    }
    return response.data
  } catch (error) {
    const message = error instanceof Error ? error.message : (error as { errMsg?: string }).errMsg
    throw new Error(message || '无法连接本地服务，请确认后端已启动')
  }
}

export async function uploadFile<T>(path: string, filePath: string, formData?: Record<string, string>): Promise<T> {
  try {
    const response = await Taro.uploadFile({
      url: `${API_BASE_URL}${path}`,
      filePath,
      name: 'file',
      formData,
      timeout: 30000
    })
    const body = response.data ? JSON.parse(response.data) : {}
    if (response.statusCode < 200 || response.statusCode >= 300) throw new Error(body.detail || `上传失败（${response.statusCode}）`)
    return body as T
  } catch (error) {
    const message = error instanceof Error ? error.message : (error as { errMsg?: string }).errMsg
    throw new Error(message || '文件上传失败，请检查后端连接')
  }
}

export function absoluteFileUrl(path: string) {
  return /^https?:\/\//.test(path) ? path : `${API_BASE_URL}${path}`
}
