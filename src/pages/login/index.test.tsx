import Taro from '@tarojs/taro'
import { act, create } from 'react-test-renderer'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuth } from '../../context/AuthContext'
import LoginPage from './index'

vi.mock('@tarojs/taro', () => ({ default: { reLaunch: vi.fn() } }))
vi.mock('@tarojs/components', () => ({ Button: 'button', Text: 'text', View: 'view' }))
vi.mock('../../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('./index.scss', () => ({}))

describe('LoginPage', () => {
  beforeEach(() => vi.resetAllMocks())

  it('shows a readable login failure and retries from the page', async () => {
    const retry = vi.fn().mockResolvedValue(undefined)
    vi.mocked(useAuth).mockReturnValue({ status: 'anonymous', user: null, error: '微信网络繁忙', retry, setUser: vi.fn() })

    const renderer = create(<LoginPage />)
    const retryButton = renderer.root.findByType('button')

    expect(JSON.stringify(renderer.toJSON())).toContain('微信网络繁忙')
    await act(async () => retryButton.props.onClick())
    expect(retry).toHaveBeenCalledTimes(1)
  })

  it('reLaunches the workbench after a complete identity is authenticated', async () => {
    vi.mocked(useAuth).mockReturnValue({
      status: 'authenticated',
      user: { id: 'user-1', technician_name: '王师傅', role: 'technician', profile_complete: true },
      error: '', retry: vi.fn(), setUser: vi.fn()
    })

    await act(async () => { create(<LoginPage />) })

    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/pages/workbench/index' })
  })

  it('reLaunches the profile page when technician identity is incomplete', async () => {
    vi.mocked(useAuth).mockReturnValue({
      status: 'authenticated',
      user: { id: 'user-2', technician_name: null, role: 'technician', profile_complete: false },
      error: '', retry: vi.fn(), setUser: vi.fn()
    })

    await act(async () => { create(<LoginPage />) })

    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/pages/profile/index' })
  })
})
