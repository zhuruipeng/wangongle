import Taro from '@tarojs/taro'
import { act, create } from 'react-test-renderer'
import { beforeEach, expect, it, vi } from 'vitest'
import { useAuth } from './AuthContext'
import { DeliveryProvider, useDelivery } from './DeliveryContext'

vi.mock('@tarojs/taro', () => ({
  default: { getStorageSync: vi.fn(), setStorageSync: vi.fn(), removeStorageSync: vi.fn() }
}))
vi.mock('./AuthContext', () => ({ useAuth: vi.fn() }))

function Probe() {
  useDelivery()
  return null
}

beforeEach(() => vi.resetAllMocks())

it('clears a persisted delivery when the session becomes anonymous', async () => {
  vi.mocked(Taro.getStorageSync).mockReturnValue('order-from-old-session')
  vi.mocked(useAuth).mockReturnValue({ status: 'anonymous', user: null, error: '', retry: vi.fn(), setUser: vi.fn() })

  await act(async () => { create(<DeliveryProvider><Probe /></DeliveryProvider>) })

  expect(Taro.removeStorageSync).toHaveBeenCalledWith('ganwanleServiceOrderId')
})
