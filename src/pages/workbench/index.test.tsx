import Taro from '@tarojs/taro'
import { act, create } from 'react-test-renderer'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuth } from '../../context/AuthContext'
import { useDelivery } from '../../context/DeliveryContext'
import { createServiceOrder, listServiceOrders } from '../../services/serviceOrders'
import Workbench from './index'

const taroHooks = vi.hoisted(() => ({ didShow: undefined as undefined | (() => void | Promise<void>) }))

vi.mock('@tarojs/taro', () => ({
  default: { navigateTo: vi.fn(), showToast: vi.fn() },
  useDidShow: vi.fn((callback: () => void | Promise<void>) => { taroHooks.didShow = callback })
}))
vi.mock('@tarojs/components', () => ({ Button: 'button', Input: 'input', Text: 'text', View: 'view' }))
vi.mock('../../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../../context/DeliveryContext', () => ({ useDelivery: vi.fn() }))
vi.mock('../../services/serviceOrders', () => ({ createServiceOrder: vi.fn(), listServiceOrders: vi.fn() }))
vi.mock('../../components/OrderSummary', () => ({ default: () => null }))
vi.mock('./index.scss', () => ({}))

const order = {
  id: 'order-1', order_no: 'GW-1-ABC123', company_name: '安心空调服务', customer_name: '王先生',
  customer_phone: '138****6688', service_address: '临沂市兰山区金雀山路', service_type: '空调安装',
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
    vi.mocked(Taro.navigateTo).mockResolvedValue({ errMsg: 'navigateTo:ok' })
  })

  const fillDraft = async (renderer: ReturnType<typeof create>) => {
    const values = ['安心空调服务', '李先生', '13900001111', '临沂市兰山区测试路1号', '空调维修']
    const inputs = renderer.root.findAllByType('input')
    for (let index = 0; index < inputs.length; index += 1) {
      await act(async () => inputs[index].props.onInput({ detail: { value: values[index] } }))
    }
  }

  it('loads only the authenticated API order list when shown', async () => {
    vi.mocked(listServiceOrders).mockResolvedValue([order] as never)

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })

    expect(listServiceOrders).toHaveBeenCalledTimes(1)
    expect(JSON.stringify(renderer.toJSON())).toContain('GW-1-ABC123')
    expect(JSON.stringify(renderer.toJSON())).toContain('王先生')
  })

  it('requires complete customer and service details before creation', async () => {
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    await act(async () => renderer.root.findByType('button').props.onClick())

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
    await act(async () => renderer.root.findByType('button').props.onClick())

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

  it('does not recover a creation failure through a global order search', async () => {
    vi.mocked(createServiceOrder).mockRejectedValue(new Error('订单创建失败'))

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    await fillDraft(renderer)
    vi.mocked(listServiceOrders).mockClear()
    await act(async () => renderer.root.findByType('button').props.onClick())

    expect(listServiceOrders).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(expect.objectContaining({ title: '订单创建失败' }))
  })
})
