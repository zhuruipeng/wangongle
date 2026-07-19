import Taro from '@tarojs/taro'
import { act, create } from 'react-test-renderer'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiRequest } from '../services/api'
import { getAccessToken, loginWithWechat } from '../services/session'
import { AuthProvider, useAuth, type AuthContextValue } from './AuthContext'

vi.mock('@tarojs/taro', () => ({
  default: { getLaunchOptionsSync: vi.fn(() => ({ path: 'pages/login/index', query: {} })) }
}))
vi.mock('../services/api', () => ({ apiRequest: vi.fn() }))
vi.mock('../services/session', () => ({
  clearSession: vi.fn(),
  getAccessToken: vi.fn(),
  loginWithWechat: vi.fn()
}))

let currentAuth: AuthContextValue | null = null

function Probe() {
  currentAuth = useAuth()
  return null
}

async function renderProvider() {
  await act(async () => {
    create(<AuthProvider><Probe /></AuthProvider>)
  })
}

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    currentAuth = null
    vi.mocked(Taro.getLaunchOptionsSync).mockReturnValue({ path: 'pages/login/index', query: {} } as never)
    vi.mocked(getAccessToken).mockReturnValue('')
  })

  it('uses WeChat login when there is no persisted access token', async () => {
    const user = { id: 'user-1', technician_name: '王师傅', role: 'technician' as const, profile_complete: true }
    vi.mocked(loginWithWechat).mockResolvedValue({ access_token: 'access', refresh_token: 'refresh', user })

    await renderProvider()

    expect(apiRequest).not.toHaveBeenCalled()
    expect(loginWithWechat).toHaveBeenCalledTimes(1)
    expect(currentAuth).toMatchObject({ status: 'authenticated', user, error: '' })
  })

  it('restores the authenticated user from /me when an access token exists', async () => {
    const user = { id: 'user-1', technician_name: '李师傅', role: 'technician' as const, profile_complete: true }
    vi.mocked(getAccessToken).mockReturnValue('stored-access')
    vi.mocked(apiRequest).mockResolvedValue(user)

    await renderProvider()

    expect(apiRequest).toHaveBeenCalledWith('/api/v1/auth/me')
    expect(loginWithWechat).not.toHaveBeenCalled()
    expect(currentAuth).toMatchObject({ status: 'authenticated', user })
  })

  it('falls back to WeChat login when a persisted session cannot restore /me', async () => {
    const user = { id: 'user-2', technician_name: '新师傅', role: 'technician' as const, profile_complete: true }
    vi.mocked(getAccessToken).mockReturnValue('expired-access')
    vi.mocked(apiRequest).mockRejectedValue(new Error('登录已过期'))
    vi.mocked(loginWithWechat).mockResolvedValue({ access_token: 'new-access', refresh_token: 'new-refresh', user })

    await renderProvider()

    expect(apiRequest).toHaveBeenCalledWith('/api/v1/auth/me')
    expect(loginWithWechat).toHaveBeenCalledTimes(1)
    expect(currentAuth).toMatchObject({ status: 'authenticated', user, error: '' })
  })

  it('keeps an incomplete user authenticated so shared customer pages can remain open', async () => {
    const user = { id: 'user-1', technician_name: null, role: 'technician' as const, profile_complete: false }
    vi.mocked(loginWithWechat).mockResolvedValue({ access_token: 'access', refresh_token: 'refresh', user })

    await renderProvider()

    expect(currentAuth).toMatchObject({ status: 'authenticated', user })
  })

  it('skips technician authentication on a cold customer share launch', async () => {
    vi.mocked(Taro.getLaunchOptionsSync).mockReturnValue({
      path: 'pages/customer-acceptance/index',
      query: { shareToken: 'customer-token' }
    } as never)

    await renderProvider()

    expect(loginWithWechat).not.toHaveBeenCalled()
    expect(apiRequest).not.toHaveBeenCalled()
    expect(currentAuth).toMatchObject({ status: 'anonymous', user: null, error: '' })
  })

  it('exposes an anonymous error state and can retry login', async () => {
    const user = { id: 'user-1', technician_name: '赵师傅', role: 'technician' as const, profile_complete: true }
    vi.mocked(loginWithWechat)
      .mockRejectedValueOnce(new Error('微信网络繁忙'))
      .mockResolvedValueOnce({ access_token: 'access', refresh_token: 'refresh', user })

    await renderProvider()

    expect(currentAuth).toMatchObject({ status: 'anonymous', error: '微信网络繁忙' })

    await act(async () => {
      await currentAuth?.retry()
    })

    expect(loginWithWechat).toHaveBeenCalledTimes(2)
    expect(currentAuth).toMatchObject({ status: 'authenticated', user, error: '' })
  })
})
