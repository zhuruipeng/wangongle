import Taro from '@tarojs/taro'
import { act, create } from 'react-test-renderer'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDelivery } from '../../context/DeliveryContext'
import {
  acceptCustomerSharedOrder,
  acceptServiceOrder,
  createCustomerShare,
  downloadCustomerSharedOrderPdf,
  downloadOrderPdf,
  getCustomerSharedOrder,
  getServiceOrder
} from '../../services/serviceOrders'
import CustomerAcceptance from './index'

const taroHooks = vi.hoisted(() => ({
  load: undefined as undefined | (() => void),
  share: undefined as undefined | (() => { title: string; path: string }),
  params: { serviceOrderId: 'order-1' } as Record<string, string>
}))

vi.mock('@tarojs/taro', () => ({
  default: {
    canvasToTempFilePath: vi.fn(),
    openDocument: vi.fn(),
    getCurrentInstance: vi.fn(() => ({ router: { params: taroHooks.params } })),
    reLaunch: vi.fn(),
    showModal: vi.fn(),
    showToast: vi.fn()
  },
  getCurrentInstance: vi.fn(() => ({ router: { params: taroHooks.params } })),
  useLoad: vi.fn((callback: () => void) => { taroHooks.load = callback }),
  useShareAppMessage: vi.fn((callback: () => { title: string; path: string }) => { taroHooks.share = callback })
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
vi.mock('../../services/serviceOrders', () => ({
  acceptCustomerSharedOrder: vi.fn(),
  acceptServiceOrder: vi.fn(),
  createCustomerShare: vi.fn(),
  downloadCustomerSharedOrderPdf: vi.fn(),
  downloadOrderPdf: vi.fn(),
  getCustomerSharedOrder: vi.fn(),
  getServiceOrder: vi.fn()
}))
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
  const selectServiceOrder = vi.fn()
  let currentOrder: typeof order | null

  beforeEach(() => {
    vi.resetAllMocks()
    taroHooks.load = undefined
    taroHooks.share = undefined
    taroHooks.params = { serviceOrderId: 'order-1' }
    currentOrder = null
    vi.mocked(useDelivery).mockImplementation(() => ({
      serviceOrderId: 'order-1',
      remoteOrder: currentOrder,
      beforePhotos: [],
      afterPhotos: [],
      setServiceOrderId,
      setRemoteOrder,
      selectServiceOrder
    } as never))
    vi.mocked(getServiceOrder).mockResolvedValue(order as never)
    vi.mocked(getCustomerSharedOrder).mockResolvedValue(order as never)
    vi.mocked(createCustomerShare).mockResolvedValue({ share_token: 'share-token', expires_in: 2592000 })
    vi.mocked(downloadOrderPdf).mockResolvedValue('/tmp/order-report.pdf')
    vi.mocked(downloadCustomerSharedOrderPdf).mockResolvedValue('/tmp/shared-report.pdf')
    vi.mocked(Taro.canvasToTempFilePath).mockResolvedValue({ tempFilePath: '/tmp/signature.png', errMsg: 'ok' })
    vi.mocked(acceptServiceOrder).mockResolvedValue({
      status: 'accepted',
      acceptance: { id: 'acceptance-1', accepted_at: '2026-07-19T14:00:00Z', signature_url: '/signature' }
    })
    vi.mocked(acceptCustomerSharedOrder).mockResolvedValue({
      status: 'accepted',
      acceptance: { id: 'acceptance-2', accepted_at: '2026-07-19T14:00:00Z', signature_url: '/signature' }
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

  it('builds a WeChat chat card with a customer share token', async () => {
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<CustomerAcceptance />) })
    await act(async () => {
      currentOrder = order
      taroHooks.load?.()
      await Promise.resolve()
      await Promise.resolve()
      renderer.update(<CustomerAcceptance />)
    })

    expect(createCustomerShare).toHaveBeenCalledWith('order-1')
    expect(taroHooks.share?.()).toEqual(expect.objectContaining({
      title: '安心空调服务服务单，请您确认验收',
      path: '/pages/customer-acceptance/index?shareToken=share-token'
    }))
    const shareButton = renderer.root.findAllByType('button').find(button => button.props.openType === 'share')
    expect(shareButton?.props.disabled).toBe(false)
  })

  it('loads and accepts a shared order without the authenticated order API', async () => {
    taroHooks.params = { shareToken: 'customer-token' }
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<CustomerAcceptance />) })
    await act(async () => {
      taroHooks.load?.()
      await Promise.resolve()
      await Promise.resolve()
    })

    await act(async () => renderer.root.findByType('checkbox-group' as never).props.onChange({ detail: { value: ['accepted'] } }))
    const buttons = renderer.root.findAllByType('button')
    await act(async () => buttons.find(button => button.props['data-signature'])?.props.onClick())
    await act(async () => buttons[buttons.length - 1].props.onClick())

    expect(getCustomerSharedOrder).toHaveBeenCalledWith('customer-token')
    expect(getServiceOrder).not.toHaveBeenCalled()
    expect(createCustomerShare).not.toHaveBeenCalled()
    expect(acceptCustomerSharedOrder).toHaveBeenCalledWith('customer-token', '/tmp/signature.png')
    expect(acceptServiceOrder).not.toHaveBeenCalled()
  })

  it('opens the latest PDF with the WeChat document menu', async () => {
    currentOrder = order
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<CustomerAcceptance />) })
    await act(async () => {
      taroHooks.load?.()
      await Promise.resolve()
      await Promise.resolve()
    })

    const pdfButton = renderer.root.findAllByType('button').find(button =>
      String(button.props.children).includes('查看并保存 PDF')
    )
    await act(async () => pdfButton?.props.onClick())

    expect(downloadOrderPdf).toHaveBeenCalledWith('order-1')
    expect(Taro.openDocument).toHaveBeenCalledWith({
      filePath: '/tmp/order-report.pdf',
      fileType: 'pdf',
      showMenu: true
    })
  })

  it('uses the public PDF endpoint in customer share mode', async () => {
    taroHooks.params = { shareToken: 'customer-token' }
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<CustomerAcceptance />) })
    await act(async () => {
      taroHooks.load?.()
      await Promise.resolve()
      await Promise.resolve()
    })

    const pdfButton = renderer.root.findAllByType('button').find(button =>
      String(button.props.children).includes('查看并保存 PDF')
    )
    await act(async () => pdfButton?.props.onClick())

    expect(downloadCustomerSharedOrderPdf).toHaveBeenCalledWith('customer-token')
    expect(downloadOrderPdf).not.toHaveBeenCalled()
    expect(Taro.openDocument).toHaveBeenCalledWith(expect.objectContaining({
      filePath: '/tmp/shared-report.pdf',
      showMenu: true
    }))
  })

  it('returns to the workbench from an accepted order', async () => {
    currentOrder = { ...order, status: 'accepted' } as never
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<CustomerAcceptance />) })
    const buttons = renderer.root.findAllByType('button')
    const primaryButton = buttons[buttons.length - 1]
    await act(async () => primaryButton?.props.onClick())

    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/pages/workbench/index' })
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
