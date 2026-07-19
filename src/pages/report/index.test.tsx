import Taro from '@tarojs/taro'
import { act, create } from 'react-test-renderer'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDelivery } from '../../context/DeliveryContext'
import { generateAiOrderReport, saveAiOrderReport, submitOrderAcceptance, type ApiAiServiceReportDraft } from '../../services/serviceOrders'
import ReportPage from './index'

vi.mock('@tarojs/taro', () => ({ default: { showToast: vi.fn(), redirectTo: vi.fn() } }))
vi.mock('@tarojs/components', () => ({ Button: 'button', Input: 'input', Text: 'text', Textarea: 'textarea', View: 'view' }))
vi.mock('../../components/StepProgress', () => ({ default: () => null }))
vi.mock('../../context/DeliveryContext', () => ({ useDelivery: vi.fn() }))
vi.mock('../../services/serviceOrders', () => ({ generateAiOrderReport: vi.fn(), saveAiOrderReport: vi.fn(), submitOrderAcceptance: vi.fn() }))
vi.mock('./index.scss', () => ({}))

const report: ApiAiServiceReportDraft = {
  service_title: '空调安装服务报告',
  service_type: '空调安装',
  work_summary: '完成空调安装。',
  before_status: null,
  after_status: null,
  completed_items: [{ content: '完成空调安装', source: 'user_text' }],
  materials: [{ name: { value: '铜管', source: 'user_text' }, quantity: { value: '2米', source: 'user_text' }, amount_cents: { value: null, source: 'unknown' } }],
  labor: [],
  risks: [],
  exceptions: [],
  customer_confirmation_text: '请客户确认本次服务已完成。',
  needs_confirmation: ['铜管费用未提供，需要师傅确认']
}

describe('ReportPage AI report V1', () => {
  const setAiReport = vi.fn()
  const setRemoteOrder = vi.fn()

  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useDelivery).mockReturnValue({
      serviceOrderId: 'order-1',
      remoteOrder: { id: 'order-1', service_type: '空调安装', transcript: '完成空调安装，用了两米铜管。', ai_report: null },
      aiReport: null,
      setAiReport,
      setRemoteOrder,
      description: '完成空调安装，用了两米铜管。'
    } as never)
  })

  it('generates a structured draft with manual supplement text', async () => {
    vi.mocked(generateAiOrderReport).mockResolvedValue({ status: 'succeeded', report, model: 'qwen3.5-plus-2026-02-15' })
    const renderer = create(<ReportPage />)

    await act(async () => renderer.root.findAllByType('textarea')[0].props.onInput({ detail: { value: '客户补充外机位置偏高' } }))
    await act(async () => renderer.root.findAllByType('button')[0].props.onClick())

    expect(generateAiOrderReport).toHaveBeenCalledWith('order-1', '客户补充外机位置偏高', false)
    expect(setAiReport).toHaveBeenCalledWith(report)
  })

  it('renders clearly labeled basic report fields', () => {
    vi.mocked(useDelivery).mockReturnValue({
      serviceOrderId: 'order-1',
      remoteOrder: { id: 'order-1', service_type: '空调安装', transcript: '完成空调安装。', ai_report: report },
      aiReport: report,
      setAiReport,
      setRemoteOrder,
      description: '完成空调安装。'
    } as never)
    const renderer = create(<ReportPage />)
    const output = JSON.stringify(renderer.toJSON())

    expect(output).toContain('报告标题')
    expect(output).toContain('服务类型')
    expect(output).toContain('服务概述')
    expect(renderer.root.findAllByType('input').slice(0, 2).every(input => input.props.className === 'text-input')).toBe(true)
  })

  it('saves the edited report and opens customer acceptance', async () => {
    vi.mocked(useDelivery).mockReturnValue({
      serviceOrderId: 'order-1',
      remoteOrder: { id: 'order-1', service_type: '空调安装', transcript: '完成空调安装。', ai_report: null },
      aiReport: report,
      setAiReport,
      setRemoteOrder,
      description: '完成空调安装。'
    } as never)
    vi.mocked(saveAiOrderReport).mockResolvedValue({ id: 'order-1', ai_report: report } as never)
    vi.mocked(submitOrderAcceptance).mockResolvedValue({ id: 'order-1', status: 'waiting_acceptance', ai_report: report } as never)
    const renderer = create(<ReportPage />)
    const buttons = renderer.root.findAllByType('button')

    await act(async () => buttons[buttons.length - 1].props.onClick())

    expect(saveAiOrderReport).toHaveBeenCalledWith('order-1', report)
    expect(submitOrderAcceptance).toHaveBeenCalledWith('order-1')
    expect(setRemoteOrder).toHaveBeenCalledWith({ id: 'order-1', status: 'waiting_acceptance', ai_report: report })
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: '/pages/customer-acceptance/index?serviceOrderId=order-1' })
  })
})
