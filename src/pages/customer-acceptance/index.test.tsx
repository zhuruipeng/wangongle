import Taro from '@tarojs/taro'
import { act, create } from 'react-test-renderer'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDelivery } from '../../context/DeliveryContext'
import { acceptServiceOrder, getServiceOrder } from '../../services/serviceOrders'
import CustomerAcceptance from './index'

const taroHooks = vi.hoisted(() => ({ load: undefined as undefined | (() => void) }))

vi.mock('@tarojs/taro', () => ({
  default: {
    canvasToTempFilePath: vi.fn(),
    getCurrentInstance: vi.fn(() => ({ router: { params: { serviceOrderId: 'order-1' } } })),
    showModal: vi.fn(),
    showToast: vi.fn()
  },
  getCurrentInstance: vi.fn(() => ({ router: { params: { serviceOrderId: 'order-1' } } })),
  useLoad: vi.fn((callback: () => void) => { taroHooks.load = callback })
}))
vi.mock('@tarojs/components', () => ({
  Button: 'button',
  Checkbox: 'checkbox',
  CheckboxGroup: 'checkbox-group',
  Image: 'image',
  Text: 'text',
  View: 'view'
}))
vi.mock('../../components/SignaturePad', () => ({
  default: ({ onSignedChange }: { onSignedChange: (signed: boolean) => void }) =>
    <button data-signature onClick={() => onSignedChange(true)}>签名</button>
}))
vi.mock('../../context/DeliveryContext', () => ({ useDelivery: vi.fn() }))
vi.mock('../../services/serviceOrders', () => ({ acceptServiceOrder: vi.fn(), getServiceOrder: vi.fn() }))
vi.mock('../../services/api', () => ({ absoluteFileUrl: (path: string) => path }))
vi.mock('./index.scss', () => ({}))

const report = {
  service_title: '空调维修报告',
  service_type: '空调维修',
  work_summary: '维修完成',
  before_status: null,
  after_status: null,
  completed_items: [{ content: '完成检修', source: 'user_text' as const }],
  materials: [],
  labor: [],
  risks: [],
  exceptions: [],
  customer_confirmation_text: '客户确认维修完成',
  needs_confirmation: []
}
const order = {
  id: 'order-1',
  order_no: 'GW-1',
  company_name: '安心空调服务',
  customer_name: '李先生',
  customer_phone: '13900001111',
  service_address: '测试路1号',
  service_type: '空调维修',
  technician_name: '王师傅',
  status: 'waiting_acceptance' as const,
  report: null,
  ai_report: report,
  paid_amount_cents: 0,
  before_photos: [],
  after_photos: []
}

describe('CustomerAcceptance', () => {
  const setServiceOrderId = vi.fn()
  const setRemoteOrder = vi.fn()
  let currentOrder: typeof order | null

  beforeEach(() => {
    vi.resetAllMocks()
    taroHooks.load = undefined
    currentOrder = null
    vi.mocked(useDelivery).mockImplementation(() => ({
      serviceOrderId: 'order-1',
      remoteOrder: currentOrder,
      beforePhotos: [],
      afterPhotos: [],
      setServiceOrderId,
      setRemoteOrder
    } as never))
    vi.mocked(getServiceOrder).mockResolvedValue(order as never)
    vi.mocked(Taro.canvasToTempFilePath).mockResolvedValue({ tempFilePath: '/tmp/signature.png', errMsg: 'ok' })
    vi.mocked(acceptServiceOrder).mockResolvedValue({
      status: 'accepted',
      acceptance: { id: 'acceptance-1', accepted_at: '2026-07-19T14:00:00Z', signature_url: '/signature' }
    })
  })

  it('exports and uploads the customer signature before showing success', async () => {
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<CustomerAcceptance />) })
    await act(async () => {
      currentOrder = order
      taroHooks.load?.()
      await Promise.resolve()
      renderer.update(<CustomerAcceptance />)
    })

    await act(async () => renderer.root.findByType('checkbox-group' as never).props.onChange({ detail: { value: ['accepted'] } }))
    const buttons = renderer.root.findAllByType('button')
    await act(async () => buttons.find(button => button.props['data-signature'])?.props.onClick())
    await act(async () => buttons[buttons.length - 1].props.onClick())

    expect(Taro.canvasToTempFilePath).toHaveBeenCalledWith(expect.objectContaining({ canvasId: 'customerSignature', fileType: 'png' }))
    expect(acceptServiceOrder).toHaveBeenCalledWith('order-1', '/tmp/signature.png')
    expect(setRemoteOrder).toHaveBeenCalledWith(expect.objectContaining({ status: 'accepted' }))
    expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({ title: '验收成功' }))
  })

  it('does not fall back to simulated customer data when loading fails', async () => {
    vi.mocked(getServiceOrder).mockRejectedValue(new Error('服务单不存在'))
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<CustomerAcceptance />) })
    await act(async () => {
      taroHooks.load?.()
      await Promise.resolve()
    })

    const output = JSON.stringify(renderer.toJSON())
    expect(output).toContain('服务单不存在')
    expect(output).not.toContain('王先生')
  })
})
