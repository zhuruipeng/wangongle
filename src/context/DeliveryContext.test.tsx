import Taro from '@tarojs/taro'
import { act, create, type ReactTestRenderer } from 'react-test-renderer'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuth, type AuthContextValue } from './AuthContext'
import { DeliveryProvider, useDelivery } from './DeliveryContext'

vi.mock('@tarojs/taro', () => ({
  default: { getStorageSync: vi.fn(), setStorageSync: vi.fn(), removeStorageSync: vi.fn() }
}))
vi.mock('./AuthContext', () => ({ useAuth: vi.fn() }))

let authValue: AuthContextValue
let currentOrderId = ''
let observedOrderIds: string[] = []

function Probe() {
  currentOrderId = useDelivery().serviceOrderId
  observedOrderIds.push(currentOrderId)
  return null
}

function auth(status: AuthContextValue['status'], id?: string, profileComplete = true): AuthContextValue {
  return {
    status,
    user: id ? { id, technician_name: '王师傅', role: 'technician', profile_complete: profileComplete } : null,
    error: '', retry: vi.fn(), setUser: vi.fn()
  }
}

async function renderProvider(): Promise<ReactTestRenderer> {
  let renderer!: ReactTestRenderer
  await act(async () => { renderer = create(<DeliveryProvider><Probe /></DeliveryProvider>) })
  return renderer
}

describe('DeliveryProvider authenticated persistence', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    currentOrderId = ''
    observedOrderIds = []
    vi.mocked(useAuth).mockImplementation(() => authValue)
  })

  it.each([
    ['loading', auth('loading')],
    ['anonymous', auth('anonymous')],
    ['incomplete profile', auth('authenticated', 'user-a', false)]
  ])('does not hydrate storage while auth is %s', async (_label, state) => {
    authValue = state

    await renderProvider()

    expect(Taro.getStorageSync).not.toHaveBeenCalled()
    expect(currentOrderId).toBe('')
  })

  it('hydrates and persists only the completed authenticated user key', async () => {
    authValue = auth('authenticated', 'user-a')
    vi.mocked(Taro.getStorageSync).mockReturnValue('order-a')

    await renderProvider()

    expect(Taro.getStorageSync).toHaveBeenCalledWith('ganwanleServiceOrderId:user-a')
    expect(currentOrderId).toBe('order-a')
  })

  it('clears in-memory delivery before hydrating a different authenticated user', async () => {
    authValue = auth('authenticated', 'user-a')
    vi.mocked(Taro.getStorageSync).mockImplementation((key: string) => key.endsWith('user-a') ? 'order-a' : 'order-b')
    const renderer = await renderProvider()
    observedOrderIds = []

    authValue = auth('authenticated', 'user-b')
    await act(async () => { renderer.update(<DeliveryProvider><Probe /></DeliveryProvider>) })

    expect(Taro.getStorageSync).toHaveBeenLastCalledWith('ganwanleServiceOrderId:user-b')
    expect(observedOrderIds).toContain('')
    expect(currentOrderId).toBe('order-b')
  })

  it('does not inherit the old order when login fallback resolves to another user', async () => {
    authValue = auth('authenticated', 'old-user')
    vi.mocked(Taro.getStorageSync).mockImplementation((key: string) => key.endsWith('old-user') ? 'old-order' : '')
    const renderer = await renderProvider()

    authValue = auth('authenticated', 'wechat-user')
    await act(async () => { renderer.update(<DeliveryProvider><Probe /></DeliveryProvider>) })

    expect(currentOrderId).toBe('')
    expect(Taro.getStorageSync).toHaveBeenLastCalledWith('ganwanleServiceOrderId:wechat-user')
  })
})
