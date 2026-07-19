import { act, create } from 'react-test-renderer'
import { describe, expect, it, vi } from 'vitest'
import { useDelivery } from '../../context/DeliveryContext'
import Voice from './index'

vi.mock('@tarojs/taro', () => ({
  default: {
    getRecorderManager: vi.fn(() => { throw new Error('recorder unavailable') }),
    navigateTo: vi.fn(),
    showToast: vi.fn()
  }
}))
vi.mock('@tarojs/components', () => ({
  Button: 'button',
  Text: 'text',
  Textarea: 'textarea',
  View: 'view'
}))
vi.mock('../../components/StepProgress', () => ({ default: () => null }))
vi.mock('../../context/DeliveryContext', () => ({ useDelivery: vi.fn() }))
vi.mock('../../services/serviceOrders', () => ({
  patchServiceOrder: vi.fn(),
  transcribeOrderAudio: vi.fn(),
  uploadOrderAudio: vi.fn()
}))
vi.mock('./index.scss', () => ({}))

describe('Voice recorder fallback', () => {
  it('keeps manual input visible when the recorder API is unavailable', async () => {
    vi.mocked(useDelivery).mockReturnValue({
      serviceOrderId: 'order-1',
      voicePath: '',
      description: '',
      setVoicePath: vi.fn(),
      setDescription: vi.fn(),
      setAiReport: vi.fn(),
      setRemoteOrder: vi.fn()
    } as never)

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Voice />) })

    const output = JSON.stringify(renderer.toJSON())
    expect(output).toContain('当前环境无法使用录音，可直接输入文字')
    expect(output).toContain('手动输入或修改识别文字')
    expect(renderer.root.findAllByType('textarea')).toHaveLength(1)
  })
})
