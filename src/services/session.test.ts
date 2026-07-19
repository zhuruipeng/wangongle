import Taro from '@tarojs/taro'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearSession, getAccessToken, getRefreshToken, loginWithWechat, refreshSession, saveSession } from './session'

vi.mock('@tarojs/taro', () => ({
  default: {
    login: vi.fn().mockResolvedValue({ code: 'wx-code' }),
    getStorageSync: vi.fn(),
    setStorageSync: vi.fn(),
    removeStorageSync: vi.fn(),
    request: vi.fn()
  }
}))

describe('session storage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('stores and clears both tokens', () => {
    saveSession({ access_token: 'access', refresh_token: 'refresh' })

    expect(Taro.setStorageSync).toHaveBeenCalledWith('ganwanleAccessToken', 'access')
    expect(Taro.setStorageSync).toHaveBeenCalledWith('ganwanleRefreshToken', 'refresh')

    clearSession()

    expect(Taro.removeStorageSync).toHaveBeenCalledWith('ganwanleAccessToken')
    expect(Taro.removeStorageSync).toHaveBeenCalledWith('ganwanleRefreshToken')
  })

  it('reads both persisted tokens', () => {
    vi.mocked(Taro.getStorageSync).mockImplementation((key: string) => key === 'ganwanleAccessToken' ? 'access' : 'refresh')

    expect(getAccessToken()).toBe('access')
    expect(getRefreshToken()).toBe('refresh')
  })

  it('rejects WeChat login when Taro returns no code', async () => {
    vi.mocked(Taro.login).mockResolvedValueOnce({ code: '', errMsg: 'login:ok' })

    await expect(loginWithWechat()).rejects.toThrow('未获取到微信登录凭证')
    expect(Taro.request).not.toHaveBeenCalled()
  })

  it('posts the WeChat code and persists both returned tokens', async () => {
    const session = {
      access_token: 'new-access',
      refresh_token: 'new-refresh',
      user: { id: 'user-1', technician_name: null, role: 'technician' as const, profile_complete: false }
    }
    vi.mocked(Taro.request).mockResolvedValueOnce({ statusCode: 200, data: session } as never)

    await expect(loginWithWechat()).resolves.toEqual(session)
    expect(Taro.request).toHaveBeenCalledWith(expect.objectContaining({
      url: 'http://localhost:8000/api/v1/auth/wechat',
      method: 'POST',
      data: { code: 'wx-code' }
    }))
    expect(Taro.setStorageSync).toHaveBeenCalledWith('ganwanleAccessToken', 'new-access')
    expect(Taro.setStorageSync).toHaveBeenCalledWith('ganwanleRefreshToken', 'new-refresh')
  })

  it('turns a failed login request into a readable retry error', async () => {
    vi.mocked(Taro.request).mockRejectedValueOnce({ errMsg: 'request:fail timeout' })

    await expect(loginWithWechat()).rejects.toThrow('request:fail timeout')
  })

  it('deduplicates concurrent refresh requests and persists the rotated pair', async () => {
    vi.mocked(Taro.getStorageSync).mockReturnValue('stored-refresh')
    let resolveRequest!: (value: unknown) => void
    vi.mocked(Taro.request).mockReturnValueOnce(new Promise(resolve => { resolveRequest = resolve }) as never)

    const first = refreshSession()
    const second = refreshSession()
    expect(Taro.request).toHaveBeenCalledTimes(1)

    const session = {
      access_token: 'rotated-access',
      refresh_token: 'rotated-refresh',
      user: { id: 'user-1', technician_name: '王师傅', role: 'technician' as const, profile_complete: true }
    }
    resolveRequest({ statusCode: 200, data: session })

    await expect(Promise.all([first, second])).resolves.toEqual([session, session])
    expect(Taro.setStorageSync).toHaveBeenCalledWith('ganwanleAccessToken', 'rotated-access')
    expect(Taro.setStorageSync).toHaveBeenCalledWith('ganwanleRefreshToken', 'rotated-refresh')
  })
})
