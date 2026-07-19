import Taro from '@tarojs/taro'
import { act, create } from 'react-test-renderer'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuth } from '../../context/AuthContext'
import { apiRequest } from '../../services/api'
import ProfilePage from './index'

vi.mock('@tarojs/taro', () => ({ default: { reLaunch: vi.fn() } }))
vi.mock('@tarojs/components', () => ({ Button: 'button', Input: 'input', Text: 'text', View: 'view' }))
vi.mock('../../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../../services/api', () => ({ apiRequest: vi.fn() }))
vi.mock('./index.scss', () => ({}))

describe('ProfilePage', () => {
  const setUser = vi.fn()

  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useAuth).mockReturnValue({
      status: 'authenticated',
      user: { id: 'user-1', technician_name: null, role: 'technician', profile_complete: false },
      error: '', retry: vi.fn(), setUser
    })
  })

  it('trims and PATCHes a valid 1-100 character technician name', async () => {
    const completedUser = { id: 'user-1', technician_name: '王师傅', role: 'technician' as const, profile_complete: true }
    vi.mocked(apiRequest).mockResolvedValue(completedUser)
    const renderer = create(<ProfilePage />)

    await act(async () => {
      renderer.root.findByType('input').props.onInput({ detail: { value: '  王师傅  ' } })
    })
    await act(async () => {
      await renderer.root.findByType('button').props.onClick()
    })

    expect(apiRequest).toHaveBeenCalledWith('/api/v1/auth/me/profile', {
      method: 'PATCH', data: { technician_name: '王师傅' }
    })
    expect(setUser).toHaveBeenCalledWith(completedUser)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/pages/workbench/index' })
  })

  it('rejects a blank or over-100-character name before requesting', async () => {
    const renderer = create(<ProfilePage />)
    const input = renderer.root.findByType('input')
    const button = renderer.root.findByType('button')

    await act(async () => button.props.onClick())
    expect(apiRequest).not.toHaveBeenCalled()

    await act(async () => input.props.onInput({ detail: { value: '师'.repeat(101) } }))
    await act(async () => renderer.root.findByType('button').props.onClick())
    expect(apiRequest).not.toHaveBeenCalled()
  })
})
