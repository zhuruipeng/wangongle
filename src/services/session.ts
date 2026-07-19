import Taro from '@tarojs/taro'

declare const __GANWANLE_API_BASE_URL__: string

const ACCESS_TOKEN_KEY = 'ganwanleAccessToken'
const REFRESH_TOKEN_KEY = 'ganwanleRefreshToken'
const API_BASE_URL = __GANWANLE_API_BASE_URL__.replace(/\/$/, '')

export type AuthUser = {
  id: string
  technician_name: string | null
  role: 'technician'
  profile_complete: boolean
}

export type SessionResponse = {
  access_token: string
  refresh_token: string
  user: AuthUser
}

export function getAccessToken(): string {
  return Taro.getStorageSync<string>(ACCESS_TOKEN_KEY) || ''
}

export function getRefreshToken(): string {
  return Taro.getStorageSync<string>(REFRESH_TOKEN_KEY) || ''
}

export function saveSession(tokens: Pick<SessionResponse, 'access_token' | 'refresh_token'>): void {
  Taro.setStorageSync(ACCESS_TOKEN_KEY, tokens.access_token)
  Taro.setStorageSync(REFRESH_TOKEN_KEY, tokens.refresh_token)
}

export function clearSession(): void {
  Taro.removeStorageSync(ACCESS_TOKEN_KEY)
  Taro.removeStorageSync(REFRESH_TOKEN_KEY)
}

function sessionError(error: unknown, fallback: string): Error {
  const message = error instanceof Error ? error.message : (error as { errMsg?: string })?.errMsg
  return new Error(message || fallback)
}

async function requestSession(path: '/api/v1/auth/wechat' | '/api/v1/auth/refresh', data: Record<string, string>): Promise<SessionResponse> {
  let response: { statusCode: number; data: SessionResponse }
  try {
    response = await Taro.request<SessionResponse>({
      url: `${API_BASE_URL}${path}`,
      method: 'POST',
      data,
      header: { 'content-type': 'application/json' },
      timeout: 15000
    })
  } catch (error) {
    throw sessionError(error, '微信登录连接失败，请重试')
  }
  if (response.statusCode < 200 || response.statusCode >= 300) {
    const detail = (response.data as unknown as { detail?: string })?.detail
    throw new Error(detail || `登录请求失败（${response.statusCode}）`)
  }
  saveSession(response.data)
  return response.data
}

export async function loginWithWechat(): Promise<SessionResponse> {
  let code: string
  try {
    code = (await Taro.login()).code
  } catch (error) {
    throw sessionError(error, '无法连接微信登录，请重试')
  }
  if (!code) throw new Error('未获取到微信登录凭证，请重试')
  return requestSession('/api/v1/auth/wechat', { code })
}

let refreshPromise: Promise<SessionResponse> | null = null

export function refreshSession(): Promise<SessionResponse> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const refreshToken = getRefreshToken()
      if (!refreshToken) throw new Error('登录已过期，请重新登录')
      return requestSession('/api/v1/auth/refresh', { refresh_token: refreshToken })
    })().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}
