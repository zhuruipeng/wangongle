import Taro from '@tarojs/taro'
import { act, create } from 'react-test-renderer'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuth } from '../../context/AuthContext'
import { useDelivery } from '../../context/DeliveryContext'
import { createServiceOrder, downloadOrderPdf, listServiceOrders } from '../../services/serviceOrders'
import Workbench from './index'

const taroHooks = vi.hoisted(() => ({ didShow: undefined as undefined | (() => void | Promise<void>) }))

vi.mock('@tarojs/taro', () => ({
  default: {
    chooseLocation: vi.fn(),
    navigateTo: vi.fn(),
    openDocument: vi.fn(),
    openLocation: vi.fn(),
    showToast: vi.fn()
  },
  useDidShow: vi.fn((callback: () => void | Promise<void>) => { taroHooks.didShow = callback })
}))
vi.mock('@tarojs/components', () => ({ Button: 'button', Input: 'input', Text: 'text', View: 'view' }))
vi.mock('../../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../../context/DeliveryContext', () => ({ useDelivery: vi.fn() }))
vi.mock('../../services/serviceOrders', () => ({
  createServiceOrder: vi.fn(),
  downloadOrderPdf: vi.fn(),
  listServiceOrders: vi.fn()
}))
vi.mock('../../components/OrderSummary', () => ({ default: () => null }))
vi.mock('./index.scss', () => ({}))

const order = {
  id: 'order-1', order_no: 'GW-1-ABC123', company_name: '安心空调服务', customer_name: '王先生',
  customer_phone: '138****6688', service_address: '临沂市兰山区金雀山路', service_type: '空调安装',
  service_location_name: null, service_latitude: null, service_longitude: null,
  technician_name: '王师傅', status: 'in_progress' as const, transcript: null, report: null, generated_report: null,
  total_amount_cents: 0, paid_amount_cents: 0, ai_report: null, audio_url: null, before_photos: [], after_photos: [],
  created_at: '2026-07-19T00:00:00Z', updated_at: '2026-07-19T00:00:00Z',
  transcription_status: 'not_started' as const, transcription_error: null, asr_request_id: null, audio_duration_ms: null,
  report_generation_status: 'not_started' as const, report_generation_error: null, report_model: null, report_generated_at: null
}

describe('Workbench identity and orders', () => {
  const selectServiceOrder = vi.fn()

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.resetAllMocks()
    taroHooks.didShow = undefined
    vi.mocked(useAuth).mockReturnValue({
      status: 'authenticated',
      user: { id: 'user-1', technician_name: '王师傅', role: 'technician', profile_complete: true },
      error: '', retry: vi.fn(), setUser: vi.fn()
    })
    vi.mocked(useDelivery).mockReturnValue({ serviceOrderId: '', selectServiceOrder } as never)
    vi.mocked(listServiceOrders).mockResolvedValue([])
    vi.mocked(downloadOrderPdf).mockResolvedValue('/tmp/service-order.pdf')
    vi.mocked(Taro.chooseLocation).mockResolvedValue({
      name: '测试大厦',
      address: '山东省临沂市兰山区测试路88号',
      latitude: 35.052345,
      longitude: 118.347891,
      errMsg: 'chooseLocation:ok'
    })
    vi.mocked(Taro.navigateTo).mockResolvedValue({ errMsg: 'navigateTo:ok' })
  })

  const fillDraft = async (renderer: ReturnType<typeof create>) => {
    const values = ['安心空调服务', '李先生', '13900001111', '临沂市兰山区测试路1号', '空调维修']
    const inputs = renderer.root.findAll(node => node.type === 'input' && node.props.confirmType !== 'search')
    for (let index = 0; index < inputs.length; index += 1) {
      await act(async () => inputs[index].props.onInput({ detail: { value: values[index] } }))
    }
  }

  const startButton = (renderer: ReturnType<typeof create>) =>
    renderer.root.findAllByType('button').find(button =>
      String(button.props.children).includes('创建并开始交付')
    )

  it('loads only the authenticated API order list when shown', async () => {
    vi.mocked(listServiceOrders).mockResolvedValue([order] as never)

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })

    expect(listServiceOrders).toHaveBeenCalledTimes(1)
    expect(JSON.stringify(renderer.toJSON())).toContain('GW-1-ABC123')
    expect(JSON.stringify(renderer.toJSON())).toContain('王先生')
  })

  it('searches recent orders across customer, phone, address and service fields', async () => {
    const secondOrder = {
      ...order,
      id: 'order-2',
      order_no: 'GW-2-XYZ789',
      customer_name: '李女士',
      customer_phone: '13900002222',
      service_address: '兰山区测试路8号',
      service_type: '热水器维修'
    }
    vi.mocked(listServiceOrders).mockResolvedValue([order, secondOrder] as never)

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    const search = renderer.root.findAllByType('input').find(input => input.props.confirmType === 'search')
    await act(async () => search?.props.onInput({ detail: { value: '热水器' } }))

    const output = JSON.stringify(renderer.toJSON())
    const resultCount = renderer.root.findAllByType('text').find(text => text.props.className === 'search-result-count')
    expect(output).toContain('李女士')
    expect(resultCount?.children.join('')).toBe('1 条匹配')
    expect(output).not.toContain('王先生')
  })

  it('shows a clear empty state when no recent order matches', async () => {
    vi.mocked(listServiceOrders).mockResolvedValue([order] as never)
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    const search = renderer.root.findAllByType('input').find(input => input.props.confirmType === 'search')
    await act(async () => search?.props.onInput({ detail: { value: '不存在的客户' } }))

    expect(JSON.stringify(renderer.toJSON())).toContain('没有找到匹配的服务单')
  })

  it('requires complete customer and service details before creation', async () => {
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    await act(async () => startButton(renderer)?.props.onClick())

    expect(createServiceOrder).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith({ title: '请完整填写服务单资料', icon: 'none' })
  })

  it('creates with a unique order number and no client-supplied technician name', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(1721347200123)
    vi.spyOn(Math, 'random').mockReturnValue(0.123456789)
    vi.mocked(createServiceOrder).mockResolvedValue(order as never)

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    await fillDraft(renderer)
    await act(async () => startButton(renderer)?.props.onClick())

    expect(createServiceOrder).toHaveBeenCalledWith(expect.objectContaining({
      order_no: expect.stringMatching(/^GW-1721347200123-[A-Z0-9]+$/)
    }))
    expect(createServiceOrder).toHaveBeenCalledWith(expect.objectContaining({
      company_name: '安心空调服务',
      customer_name: '李先生',
      customer_phone: '13900001111',
      service_address: '临沂市兰山区测试路1号',
      service_type: '空调维修'
    }))
    expect(createServiceOrder).toHaveBeenCalledWith(expect.not.objectContaining({ technician_name: expect.anything() }))
    expect(selectServiceOrder).toHaveBeenCalledWith(order)
  })

  it('resumes a recent order at the first unfinished delivery step', async () => {
    const resumable = {
      ...order,
      before_photos: [{ id: 'photo-1', phase: 'before' as const, file_url: '/before.jpg', original_filename: 'before.jpg', sort_order: 0, created_at: order.created_at }]
    }
    vi.mocked(listServiceOrders).mockResolvedValue([resumable] as never)

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    const continueButton = renderer.root.findAllByType('button').find(button => button.children.includes('继续交付'))
    await act(async () => continueButton?.props.onClick())

    expect(selectServiceOrder).toHaveBeenCalledWith(resumable)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/after-photos/index' })
  })

  it('selects a precise map location and submits its coordinates', async () => {
    vi.mocked(createServiceOrder).mockResolvedValue(order as never)
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    await fillDraft(renderer)

    const locationButton = renderer.root.findAllByType('button').find(button =>
      String(button.props.children).includes('地图选址')
    )
    await act(async () => locationButton?.props.onClick())
    await act(async () => startButton(renderer)?.props.onClick())

    expect(Taro.chooseLocation).toHaveBeenCalledWith({})
    expect(createServiceOrder).toHaveBeenCalledWith(expect.objectContaining({
      service_address: '山东省临沂市兰山区测试路88号 测试大厦',
      service_location_name: '测试大厦',
      service_latitude: 35.052345,
      service_longitude: 118.347891
    }))
  })

  it.each([
    ['waiting_acceptance', '客户验收'],
    ['accepted', '查看验收']
  ] as const)('opens %s orders in customer acceptance', async (status, actionLabel) => {
    const acceptanceOrder = { ...order, status }
    vi.mocked(listServiceOrders).mockResolvedValue([acceptanceOrder] as never)

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    const action = renderer.root.findAllByType('button').find(button => button.children.includes(actionLabel))
    await act(async () => action?.props.onClick())

    expect(selectServiceOrder).toHaveBeenCalledWith(acceptanceOrder)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/customer-acceptance/index?serviceOrderId=order-1' })
  })

  it('opens precise navigation and PDF directly from a recent order', async () => {
    const readyOrder = {
      ...order,
      service_location_name: '测试大厦',
      service_latitude: 35.052345,
      service_longitude: 118.347891,
      ai_report: { work_summary: '服务完成' }
    }
    vi.mocked(listServiceOrders).mockResolvedValue([readyOrder] as never)

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    const buttons = renderer.root.findAllByType('button')
    const mapButton = buttons.find(button => String(button.props.children).includes('地图导航'))
    const pdfButton = buttons.find(button => String(button.props.children).includes('查看 PDF'))

    await act(async () => mapButton?.props.onClick())
    await act(async () => pdfButton?.props.onClick())

    expect(Taro.openLocation).toHaveBeenCalledWith(expect.objectContaining({
      latitude: 35.052345,
      longitude: 118.347891,
      name: '测试大厦',
      scale: 18
    }))
    expect(downloadOrderPdf).toHaveBeenCalledWith('order-1')
    expect(Taro.openDocument).toHaveBeenCalledWith({
      filePath: '/tmp/service-order.pdf',
      fileType: 'pdf',
      showMenu: true
    })
  })

  it('does not recover a creation failure through a global order search', async () => {
    vi.mocked(createServiceOrder).mockRejectedValue(new Error('订单创建失败'))

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    await fillDraft(renderer)
    vi.mocked(listServiceOrders).mockClear()
    await act(async () => startButton(renderer)?.props.onClick())

    expect(listServiceOrders).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(expect.objectContaining({ title: '订单创建失败' }))
  })
})
