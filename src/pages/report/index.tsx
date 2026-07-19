import Taro from '@tarojs/taro'
import { Button, Input, Text, Textarea, View } from '@tarojs/components'
import { useEffect, useMemo, useState } from 'react'
import StepProgress from '../../components/StepProgress'
import { useDelivery } from '../../context/DeliveryContext'
import { generateAiOrderReport, saveAiOrderReport, type ApiAiReportMoneyValue, type ApiAiReportSourceValue, type ApiAiServiceReportDraft } from '../../services/serviceOrders'
import './index.scss'

const unknownText = (): ApiAiReportSourceValue => ({ value: null, source: 'unknown' })
const unknownMoney = (): ApiAiReportMoneyValue => ({ value: null, source: 'unknown' })
const manualText = (value: string): ApiAiReportSourceValue => value.trim() ? { value, source: 'manual_input' } : unknownText()
const manualMoney = (value: string): ApiAiReportMoneyValue => value.trim() ? { value: Math.round((Number(value) || 0) * 100), source: 'manual_input' } : unknownMoney()

function emptyReport(serviceType: string): ApiAiServiceReportDraft {
  return {
    service_title: `${serviceType || '空调服务'}服务报告`,
    service_type: serviceType || '空调安装',
    work_summary: null,
    before_status: null,
    after_status: null,
    completed_items: [],
    materials: [],
    labor: [],
    risks: [],
    exceptions: [],
    customer_confirmation_text: null,
    needs_confirmation: []
  }
}

function sourceLabel(source: string): string {
  if (source === 'user_text') return '来源：语音文字'
  if (source === 'manual_input') return '来源：手动补充'
  return '来源：未知'
}

export default function ReportPage() {
  const { serviceOrderId, remoteOrder, aiReport, setAiReport, setRemoteOrder, description } = useDelivery()
  const [manualSupplement, setManualSupplement] = useState('')
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)
  const serviceType = remoteOrder?.service_type || '空调安装'
  const report = useMemo(() => aiReport || remoteOrder?.ai_report || emptyReport(serviceType), [aiReport, remoteOrder?.ai_report, serviceType])

  useEffect(() => {
    if (!aiReport && remoteOrder?.ai_report) setAiReport(remoteOrder.ai_report)
  }, [aiReport, remoteOrder?.ai_report, setAiReport])

  const updateReport = (next: Partial<ApiAiServiceReportDraft>) => setAiReport({ ...report, ...next })
  const updateTextField = (key: 'service_title' | 'service_type' | 'work_summary' | 'before_status' | 'after_status' | 'customer_confirmation_text', value: string) => {
    updateReport({ [key]: value.trim() ? value : null } as Partial<ApiAiServiceReportDraft>)
  }
  const updateCompleted = (index: number, value: string) => {
    const completed = report.completed_items.map((item, itemIndex) => itemIndex === index ? { content: value, source: 'manual_input' as const } : item)
    updateReport({ completed_items: completed })
  }
  const updateMaterial = (index: number, key: 'name' | 'quantity' | 'amount_cents', value: string) => {
    const materials = report.materials.map((item, itemIndex) => {
      if (itemIndex !== index) return item
      if (key === 'amount_cents') return { ...item, amount_cents: manualMoney(value) }
      return { ...item, [key]: manualText(value) }
    })
    updateReport({ materials })
  }
  const updateLabor = (index: number, key: 'description' | 'hours' | 'amount_cents', value: string) => {
    const labor = report.labor.map((item, itemIndex) => {
      if (itemIndex !== index) return item
      if (key === 'amount_cents') return { ...item, amount_cents: manualMoney(value) }
      return { ...item, [key]: manualText(value) }
    })
    updateReport({ labor })
  }
  const updateStringList = (key: 'risks' | 'exceptions' | 'needs_confirmation', index: number, value: string) => {
    const next = report[key].map((item, itemIndex) => itemIndex === index ? value : item)
    updateReport({ [key]: next } as Partial<ApiAiServiceReportDraft>)
  }

  const generateDraft = async () => {
    if (generating) return
    if (!serviceOrderId) return Taro.showToast({ title: '缺少服务单，请从工作台重新开始', icon: 'none' })
    setGenerating(true)
    try {
      const result = await generateAiOrderReport(serviceOrderId, manualSupplement, Boolean(aiReport || remoteOrder?.ai_report))
      setAiReport(result.report)
      Taro.showToast({ title: '报告已生成', icon: 'success' })
    } catch (error) {
      Taro.showToast({ title: error instanceof Error ? error.message : '报告生成失败', icon: 'none', duration: 3000 })
    } finally {
      setGenerating(false)
    }
  }

  const saveDraft = async () => {
    if (saving) return
    if (!serviceOrderId) return Taro.showToast({ title: '缺少服务单，请从工作台重新开始', icon: 'none' })
    setSaving(true)
    try {
      const order = await saveAiOrderReport(serviceOrderId, report)
      setRemoteOrder(order)
      setAiReport(order.ai_report)
      Taro.showToast({ title: '报告已保存', icon: 'success' })
      await Taro.reLaunch({ url: '/pages/workbench/index' })
    } catch (error) {
      Taro.showToast({ title: error instanceof Error ? error.message : '报告保存失败', icon: 'none', duration: 3000 })
    } finally {
      setSaving(false)
    }
  }

  return <View className='page report-page'><StepProgress current={3} />
    <View className='ai-warning'>AI 只整理已提供的照片、语音文字和手动补充；材料、金额、工时不确定时必须为空并待师傅确认。</View>
    <View className='report-card card'>
      <Text className='section-title'>生成报告</Text>
      <Text className='source-text'>当前语音文字：{description || remoteOrder?.transcript || '未保存语音文字'}</Text>
      <Textarea className='text-area compact' value={manualSupplement} placeholder='手动补充：例如现场异常、客户确认、照片无法体现的信息' onInput={event => setManualSupplement(event.detail.value)} />
      <Button className='add-item' loading={generating} disabled={generating} onClick={generateDraft}>{generating ? '正在生成' : '生成报告'}</Button>
    </View>

    <View className='report-card card'>
      <Text className='section-title'>基础信息</Text>
      <Input className='text-input' value={report.service_title || ''} placeholder='报告标题' onInput={event => updateTextField('service_title', event.detail.value)} />
      <Input className='text-input' value={report.service_type} placeholder='服务类型' onInput={event => updateTextField('service_type', event.detail.value)} />
      <Textarea className='text-area compact' value={report.work_summary || ''} placeholder='服务概述' onInput={event => updateTextField('work_summary', event.detail.value)} />
    </View>

    <View className='report-card card'>
      <Text className='section-title'>施工前后状态</Text>
      <Textarea className='text-area compact' value={report.before_status || ''} placeholder='施工前状态，不确定可留空' onInput={event => updateTextField('before_status', event.detail.value)} />
      <Textarea className='text-area compact' value={report.after_status || ''} placeholder='施工后状态，不确定可留空' onInput={event => updateTextField('after_status', event.detail.value)} />
    </View>

    <View className='report-card card'><Text className='section-title'>完成内容</Text>
      {report.completed_items.map((item, index) => <View className='editable-item' key={index}><Input className='text-input' value={item.content} onInput={event => updateCompleted(index, event.detail.value)} /><Text className='source-text'>{sourceLabel(item.source)}</Text></View>)}
      <Button className='add-item' onClick={() => updateReport({ completed_items: [...report.completed_items, { content: '', source: 'manual_input' }] })}>+ 添加完成内容</Button>
    </View>

    <View className='report-card card'><Text className='section-title'>材料</Text>
      {report.materials.map((item, index) => <View className='material' key={index}>
        <Input className='text-input material-name' value={item.name.value || ''} placeholder='材料名称' onInput={event => updateMaterial(index, 'name', event.detail.value)} />
        <Text className='source-text'>{sourceLabel(item.name.source)}</Text>
        <Input className='text-input' value={item.quantity.value || ''} placeholder='数量，如 2米；不确定留空' onInput={event => updateMaterial(index, 'quantity', event.detail.value)} />
        <Text className='source-text'>{sourceLabel(item.quantity.source)}</Text>
        <Input className='text-input' type='digit' value={item.amount_cents.value === null ? '' : String(item.amount_cents.value / 100)} placeholder='金额（元），不确定留空' onInput={event => updateMaterial(index, 'amount_cents', event.detail.value)} />
        <Text className='source-text'>{sourceLabel(item.amount_cents.source)}</Text>
      </View>)}
      <Button className='add-item' onClick={() => updateReport({ materials: [...report.materials, { name: unknownText(), quantity: unknownText(), amount_cents: unknownMoney() }] })}>+ 添加材料</Button>
    </View>

    <View className='report-card card'><Text className='section-title'>工时与人工</Text>
      {report.labor.map((item, index) => <View className='labor-edit' key={index}>
        <Input className='text-input' value={item.description.value || ''} placeholder='人工/工时说明' onInput={event => updateLabor(index, 'description', event.detail.value)} />
        <Input className='text-input' value={item.hours.value || ''} placeholder='工时，不确定留空' onInput={event => updateLabor(index, 'hours', event.detail.value)} />
        <Input className='text-input' type='digit' value={item.amount_cents.value === null ? '' : String(item.amount_cents.value / 100)} placeholder='人工金额（元），不确定留空' onInput={event => updateLabor(index, 'amount_cents', event.detail.value)} />
      </View>)}
      <Button className='add-item' onClick={() => updateReport({ labor: [...report.labor, { description: unknownText(), hours: unknownText(), amount_cents: unknownMoney() }] })}>+ 添加工时/人工</Button>
    </View>

    <ListEditor title='风险' values={report.risks} onChange={(index, value) => updateStringList('risks', index, value)} onAdd={() => updateReport({ risks: [...report.risks, ''] })} />
    <ListEditor title='异常' values={report.exceptions} onChange={(index, value) => updateStringList('exceptions', index, value)} onAdd={() => updateReport({ exceptions: [...report.exceptions, ''] })} />
    <ListEditor title='需要师傅确认' values={report.needs_confirmation} onChange={(index, value) => updateStringList('needs_confirmation', index, value)} onAdd={() => updateReport({ needs_confirmation: [...report.needs_confirmation, ''] })} />

    <View className='report-card card'>
      <Text className='section-title'>客户确认文字</Text>
      <Textarea className='text-area compact' value={report.customer_confirmation_text || ''} placeholder='展示给客户确认的文字' onInput={event => updateTextField('customer_confirmation_text', event.detail.value)} />
    </View>

    <View className='fixed-actions'><Button className='primary-btn' loading={saving} disabled={saving} onClick={saveDraft}>保存报告</Button></View>
  </View>
}

function ListEditor({ title, values, onChange, onAdd }: { title: string; values: string[]; onChange: (index: number, value: string) => void; onAdd: () => void }) {
  return <View className='report-card card'><Text className='section-title'>{title}</Text>
    {values.map((value, index) => <Textarea className='text-area risk-input' key={index} value={value} onInput={event => onChange(index, event.detail.value)} />)}
    <Button className='add-item' onClick={onAdd}>+ 添加{title}</Button>
  </View>
}
