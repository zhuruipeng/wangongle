import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiRequest } from './api'
import { generateAiOrderReport, saveAiOrderReport, type ApiAiServiceReportDraft } from './serviceOrders'

vi.mock('./api', () => ({ apiRequest: vi.fn() }))

const report: ApiAiServiceReportDraft = {
  service_title: '空调安装服务报告',
  service_type: '空调安装',
  work_summary: '完成空调安装。',
  before_status: null,
  after_status: null,
  completed_items: [{ content: '完成空调安装', source: 'user_text' }],
  materials: [{
    name: { value: '铜管', source: 'user_text' },
    quantity: { value: '2米', source: 'user_text' },
    amount_cents: { value: null, source: 'unknown' }
  }],
  labor: [],
  risks: [],
  exceptions: [],
  customer_confirmation_text: '请客户确认本次服务已完成。',
  needs_confirmation: ['铜管费用未提供，需要师傅确认']
}

describe('AI report service API', () => {
  beforeEach(() => vi.resetAllMocks())

  it('posts manual text to the V1 AI report endpoint', async () => {
    vi.mocked(apiRequest).mockResolvedValue({ status: 'succeeded', report, model: 'qwen3.5-plus-2026-02-15' })

    await expect(generateAiOrderReport('order-1', '客户补充外机位置偏高', true))
      .resolves.toEqual({ status: 'succeeded', report, model: 'qwen3.5-plus-2026-02-15' })

    expect(apiRequest).toHaveBeenCalledWith('/api/v1/service-orders/order-1/ai-report?force=true', {
      method: 'POST',
      data: { manual_text: '客户补充外机位置偏高' },
      timeout: 120000
    })
  })

  it('saves the edited structured report draft', async () => {
    vi.mocked(apiRequest).mockResolvedValue({ id: 'order-1', ai_report: report })

    await saveAiOrderReport('order-1', report)

    expect(apiRequest).toHaveBeenCalledWith('/api/v1/service-orders/order-1/ai-report', {
      method: 'PUT',
      data: report
    })
  })
})
