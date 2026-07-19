import Taro from '@tarojs/taro'
import { clearSession, getAccessToken, refreshSession } from './session'

declare const __GANWANLE_API_BASE_URL__: string

// Replaced by Taro/Webpack at build time. Mini Program runtime has no Node.js `process` global.
export const API_BASE_URL = __GANWANLE_API_BASE_URL__.replace(/\/$/, '')

type RequestOptions = { method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'; data?: unknown; timeout?: number }

const NON_REFRESHABLE_AUTH_PATHS = new Set(['/api/v1/auth/wechat', '/api/v1/auth/refresh'])

function authHeader(): Record<string, string> {
  const accessToken = getAccessToken()
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {}
}

function responseError(data: unknown, fallback: string): Error {
  const detail = data && typeof data === 'object' ? (data as { detail?: string }).detail : undefined
  return new Error(detail || fallback)
}

function connectionError(error: unknown, fallback: string): Error {
  const message = error instanceof Error ? error.message : (error as { errMsg?: string })?.errMsg
  return new Error(message || fallback)
}

function expireSession(): void {
  clearSession()
  void Taro.reLaunch({ url: '/pages/login/index' })
}

async function recoverUnauthorized(retried: boolean): Promise<void> {
  if (retried) {
    expireSession()
    return
  }
  try {
    await refreshSession()
  } catch (error) {
    expireSession()
    throw connectionError(error, '登录已过期，请重新登录')
  }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return authenticatedRequest(path, options, false)
}

export async function publicApiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response: { statusCode: number; data: T }
  try {
    response = await Taro.request<T>({
      url: `${API_BASE_URL}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header: { 'content-type': 'application/json' },
      timeout: options.timeout || 15000
    })
  } catch (error) {
    throw connectionError(error, '无法连接服务，请稍后重试')
  }
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw responseError(response.data, `请求失败（${response.statusCode}）`)
  }
  return response.data
}

async function authenticatedRequest<T>(path: string, options: RequestOptions, retried: boolean): Promise<T> {
  let response: { statusCode: number; data: T }
  try {
    response = await Taro.request<T>({
      url: `${API_BASE_URL}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header: { 'content-type': 'application/json', ...authHeader() },
      timeout: options.timeout || 15000
    })
  } catch (error) {
    throw connectionError(error, '无法连接本地服务，请确认后端已启动')
  }
  if (response.statusCode === 401 && !NON_REFRESHABLE_AUTH_PATHS.has(path.split('?')[0])) {
    await recoverUnauthorized(retried)
    if (!retried) return authenticatedRequest(path, options, true)
  }
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw responseError(response.data, `请求失败（${response.statusCode}）`)
  }
  return response.data
}

export async function uploadFile<T>(path: string, filePath: string, formData?: Record<string, string>, fileField = 'file'): Promise<T> {
  return authenticatedUpload<T>(path, filePath, formData, fileField, false)
}

export async function publicUploadFile<T>(
  path: string,
  filePath: string,
  formData?: Record<string, string>,
  fileField = 'file'
): Promise<T> {
  let response: Taro.uploadFile.SuccessCallbackResult
  try {
    response = await Taro.uploadFile({
      url: `${API_BASE_URL}${path}`,
      filePath,
      name: fileField,
      formData,
      header: {},
      timeout: 30000
    })
  } catch (error) {
    throw connectionError(error, '文件上传失败，请检查网络后重试')
  }
  let body: { detail?: string } & Partial<T> = {}
  try {
    body = response.data ? JSON.parse(response.data) : {}
  } catch {
    throw new Error('上传响应格式错误')
  }
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw responseError(body, `上传失败（${response.statusCode}）`)
  }
  return body as T
}

async function authenticatedUpload<T>(
  path: string,
  filePath: string,
  formData: Record<string, string> | undefined,
  fileField: string,
  retried: boolean
): Promise<T> {
  let response: Taro.uploadFile.SuccessCallbackResult
  try {
    response = await Taro.uploadFile({
      url: `${API_BASE_URL}${path}`,
      filePath,
      name: fileField,
      formData,
      header: authHeader(),
      timeout: 30000
    })
  } catch (error) {
    throw connectionError(error, '文件上传失败，请检查后端连接')
  }
  if (response.statusCode === 401 && !NON_REFRESHABLE_AUTH_PATHS.has(path.split('?')[0])) {
    await recoverUnauthorized(retried)
    if (!retried) return authenticatedUpload(path, filePath, formData, fileField, true)
  }
  let body: { detail?: string } & Partial<T> = {}
  try {
    body = response.data ? JSON.parse(response.data) : {}
  } catch {
    throw new Error('上传响应格式错误')
  }
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw responseError(body, `上传失败（${response.statusCode}）`)
  }
  return body as T
}

export function absoluteFileUrl(path: string) {
  return /^https?:\/\//.test(path) ? path : `${API_BASE_URL}${path}`
}
