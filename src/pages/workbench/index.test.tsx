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
vi.mock('@tarojs/components', () => ({ Button: 'button', Text: 'text', View: 'view' }))
vi.mock('../../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../../context/DeliveryContext', () => ({ useDelivery: vi.fn() }))
vi.mock('../../services/serviceOrders', () => ({ createServiceOrder: vi.fn(), listServiceOrders: vi.fn() }))
vi.mock('../../components/OrderSummary', () => ({ default: () => null }))
vi.mock('./index.scss', () => ({}))

const order = {
  id: 'order-1', order_no: 'GW-1-ABC123', company_name: '安心空调服务', customer_name: '王先生',
  customer_phone: '138****6688', service_address: '临沂市兰山区金雀山路', service_type: '空调安装',
  technician_name: '王师傅', status: 'in_progress' as const, created_at: '2026-07-19T00:00:00Z'
}

describe('Workbench identity and orders', () => {
  const setServiceOrderId = vi.fn()
  const setRemoteOrder = vi.fn()

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.resetAllMocks()
    taroHooks.didShow = undefined
    vi.mocked(useAuth).mockReturnValue({
      status: 'authenticated',
      user: { id: 'user-1', technician_name: '王师傅', role: 'technician', profile_complete: true },
      error: '', retry: vi.fn(), setUser: vi.fn()
    })
    vi.mocked(useDelivery).mockReturnValue({ serviceOrderId: '', setServiceOrderId, setRemoteOrder } as never)
    vi.mocked(listServiceOrders).mockResolvedValue([])
    vi.mocked(Taro.navigateTo).mockResolvedValue({ errMsg: 'navigateTo:ok' })
  })

  it('loads only the authenticated API order list when shown', async () => {
    vi.mocked(listServiceOrders).mockResolvedValue([order] as never)

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })

    expect(listServiceOrders).toHaveBeenCalledTimes(1)
    expect(JSON.stringify(renderer.toJSON())).toContain('GW-1-ABC123')
    expect(JSON.stringify(renderer.toJSON())).toContain('王先生')
  })

  it('creates with a unique order number and no client-supplied technician name', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(1721347200123)
    vi.spyOn(Math, 'random').mockReturnValue(0.123456789)
    vi.mocked(createServiceOrder).mockResolvedValue(order as never)

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    await act(async () => renderer.root.findByType('button').props.onClick())

    expect(createServiceOrder).toHaveBeenCalledWith(expect.objectContaining({
      order_no: expect.stringMatching(/^GW-1721347200123-[A-Z0-9]+$/)
    }))
    expect(createServiceOrder).toHaveBeenCalledWith(expect.not.objectContaining({ technician_name: expect.anything() }))
  })

  it('does not recover a creation failure through a global order search', async () => {
    vi.mocked(createServiceOrder).mockRejectedValue(new Error('订单创建失败'))

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(<Workbench />) })
    await act(async () => { await taroHooks.didShow?.() })
    vi.mocked(listServiceOrders).mockClear()
    await act(async () => renderer.root.findByType('button').props.onClick())

    expect(listServiceOrders).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(expect.objectContaining({ title: '订单创建失败' }))
  })
})
