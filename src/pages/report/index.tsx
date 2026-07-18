import Taro from '@tarojs/taro'
import { Button, Checkbox, CheckboxGroup, Input, Text, Textarea, View } from '@tarojs/components'
import { useState } from 'react'
import StepProgress from '../../components/StepProgress'
import { useDelivery, type Report } from '../../context/DeliveryContext'
import { saveOrderReport, submitOrderAcceptance, type ApiReport } from '../../services/serviceOrders'
import './index.scss'

export default function ReportPage() {
  const { serviceOrderId, report, setReport, setRemoteOrder, generatedReport, setGeneratedReport, reportConfirmed, setReportConfirmed } = useDelivery()
  const [saving, setSaving] = useState(false)
  const number = (value: string | undefined) => Number(value) || 0
  const patch = (next: Partial<Report>) => { setReport({ ...report, ...next }); if (generatedReport) setReportConfirmed(false) }
  const materialTotal = report.materials.reduce((sum, item) => sum + number(item.price), 0)
  const laborTotal = generatedReport
    ? generatedReport.labor_items.reduce((sum, item) => sum + ((item.amount_cents || 0) / 100), 0)
    : number(report.serviceFee)
  const total = materialTotal + laborTotal
  const due = Math.max(0, total - number(report.paid))

  const updateList = (key: 'completed' | 'risks', index: number, value: string) => {
    const next = [...report[key]]; next[index] = value; patch({ [key]: next })
  }
  const updateMaterial = (index: number, key: 'name' | 'quantity' | 'unitPrice' | 'price', value: string) => {
    const materials = report.materials.map((item, itemIndex) => itemIndex === index ? { ...item, [key]: value } : item)
    if (key === 'unitPrice') {
      const quantity = parseFloat(materials[index].quantity) || 0
      materials[index].price = value.trim() && quantity ? String(Math.round(quantity * number(value) * 100) / 100) : ''
    }
    patch({ materials, materialFee: String(materials.reduce((sum, item) => sum + number(item.price), 0)) })
  }
  const updateLabor = (index: number, key: 'name' | 'amount', value: string) => {
    if (!generatedReport) return
    const laborItems = generatedReport.labor_items.map((item, itemIndex) => itemIndex === index
      ? key === 'name'
        ? { ...item, name: value }
        : { ...item, amount_cents: value.trim() ? Math.round(number(value) * 100) : null }
      : item)
    setGeneratedReport({ ...generatedReport, labor_items: laborItems })
    patch({ serviceFee: String(laborItems.reduce((sum, item) => sum + ((item.amount_cents || 0) / 100), 0)) })
  }
  const addLabor = () => {
    if (!generatedReport) return
    setGeneratedReport({ ...generatedReport, labor_items: [...generatedReport.labor_items, {
      name: '', amount_cents: null, source_text: '师傅手工补充', needs_confirmation: true
    }] })
  }
  const addMaterial = () => patch({ materials: [...report.materials, { name: '', quantity: '', unitPrice: '', price: '' }] })
  const addCompleted = () => patch({ completed: [...report.completed, ''] })
  const addRisk = () => patch({ risks: [...report.risks, ''] })

  const apiReport = (): ApiReport => ({
    completed_items: report.completed.filter(Boolean),
    materials: report.materials.filter(item => item.name.trim()).map(item => ({ name: item.name, quantity: item.quantity, amount_cents: item.price.trim() ? Math.round(number(item.price) * 100) : null })),
    fee_items: generatedReport
      ? generatedReport.labor_items.map(item => ({ name: item.name, amount_cents: item.amount_cents }))
      : [{ name: '安装服务费', amount_cents: report.serviceFee.trim() ? Math.round(number(report.serviceFee) * 100) : null }],
    risks: report.risks.filter(Boolean),
    after_sales_reminder: report.afterSales,
    total_amount_cents: Math.round(total * 100),
    paid_amount_cents: Math.round(number(report.paid) * 100)
  })

  const saveDraft = async () => {
    if (saving) return
    if (!serviceOrderId) return Taro.showToast({ title: '缺少服务单，请从工作台重新开始', icon: 'none' })
    setSaving(true)
    try {
      const order = await saveOrderReport(serviceOrderId, apiReport()); setRemoteOrder(order)
      Taro.showToast({ title: '报告已保存', icon: 'success' })
    } catch (error) { Taro.showToast({ title: error instanceof Error ? error.message : '报告保存失败', icon: 'none', duration: 3000 }) }
    finally { setSaving(false) }
  }
  const sendAcceptance = async () => {
    if (saving) return
    if (generatedReport && !reportConfirmed) return Taro.showToast({ title: '请先确认AI整理的材料、数量和金额', icon: 'none', duration: 3000 })
    if (!serviceOrderId) return Taro.showToast({ title: '缺少服务单，请从工作台重新开始', icon: 'none' })
    setSaving(true)
    try {
      await saveOrderReport(serviceOrderId, apiReport())
      const order = await submitOrderAcceptance(serviceOrderId); setRemoteOrder(order)
      Taro.showToast({ title: '已提交客户验收', icon: 'success' })
      await Taro.navigateTo({ url: `/pages/customer-acceptance/index?serviceOrderId=${encodeURIComponent(serviceOrderId)}` })
    } catch (error) { Taro.showToast({ title: error instanceof Error ? error.message : '提交验收失败', icon: 'none', duration: 3000 }) }
    finally { setSaving(false) }
  }

  return <View className='page report-page'><StepProgress current={3} />
    <View className='ai-warning'>⚠ {generatedReport ? 'AI已根据语音整理，请确认材料、数量和金额。' : 'AI内容仅供整理，请师傅确认材料和金额。'}</View>
    {generatedReport?.summary && <View className='report-card card'><Text className='section-title'>服务概述</Text><Text>{generatedReport.summary}</Text></View>}
    {!!generatedReport?.missing_information.length && <View className='missing-card'><Text className='section-title'>需要补充的信息</Text>{generatedReport.missing_information.map((item, index) => <Text key={index}>• {item}</Text>)}</View>}
    {!!generatedReport?.warnings.length && <View className='missing-card'>{generatedReport.warnings.map((item, index) => <Text key={index}>• {item}</Text>)}</View>}

    <View className='report-card card'><Text className='section-title'>1. 完成内容</Text>{report.completed.map((value, index) => <View className='editable-item' key={index}>
      <Input className='text-input' value={value} onInput={event => updateList('completed', index, event.detail.value)} />
      {generatedReport?.completed_items[index]?.source_text && <Text className='source-text'>原话：{generatedReport.completed_items[index].source_text}</Text>}
    </View>)}<Button className='add-item' onClick={addCompleted}>+ 添加完成内容</Button></View>

    <View className='report-card card'><Text className='section-title'>2. 使用材料</Text>{report.materials.map((item, index) => <View className='material' key={index}>
      <View className='item-heading'><Input className='text-input material-name' value={item.name} placeholder='材料名称' onInput={event => updateMaterial(index, 'name', event.detail.value)} />{generatedReport?.materials[index]?.needs_confirmation && <Text className='confirm-badge'>待确认</Text>}</View>
      <View className='material-row'><View><Text className='mini-label'>数量</Text><Input className='text-input' value={item.quantity} placeholder='请填写数量' onInput={event => updateMaterial(index, 'quantity', event.detail.value)} /></View><View><Text className='mini-label'>单价（元）</Text><Input className='text-input' type='digit' value={item.unitPrice || ''} placeholder='请填写单价' onInput={event => updateMaterial(index, 'unitPrice', event.detail.value)} /></View></View>
      <Text className='mini-label'>材料金额（元）</Text><Input className='text-input' type='digit' value={item.price} placeholder='请确认材料金额' onInput={event => updateMaterial(index, 'price', event.detail.value)} />
      {generatedReport?.materials[index]?.source_text && <Text className='source-text'>原话：{generatedReport.materials[index].source_text}</Text>}
    </View>)}<Button className='add-item' onClick={addMaterial}>+ 添加材料</Button></View>

    <View className='report-card card'><Text className='section-title'>3. 工时及费用</Text>
      {generatedReport ? <>{generatedReport.labor_items.map((item, index) => <View className='labor-edit' key={index}><View className='item-heading'><Input className='text-input material-name' value={item.name} placeholder='费用项目名称' onInput={event => updateLabor(index, 'name', event.detail.value)} />{item.needs_confirmation && <Text className='confirm-badge'>待确认</Text>}</View><View className='fee'><Text>金额</Text><View className='fee-input'><Text>¥</Text><Input type='digit' value={item.amount_cents === null ? '' : String(item.amount_cents / 100)} placeholder='请填写费用' onInput={event => updateLabor(index, 'amount', event.detail.value)} /></View></View><Text className='source-text'>原话：{item.source_text}</Text></View>)}<Button className='add-item' onClick={addLabor}>+ 添加费用项目</Button></> : <Fee label='安装服务费' value={report.serviceFee} onChange={value => patch({ serviceFee: value })} />}
      <View className='fee'><Text>材料费</Text><Text>¥{materialTotal}</Text></View>
      <View className='sum'><Text>合计</Text><Text>¥{total}</Text></View><Fee label='已收' value={report.paid} onChange={value => patch({ paid: value })} /><View className='sum due'><Text>待收</Text><Text>¥{due}</Text></View>
    </View>

    <View className='report-card card risk'><Text className='section-title'>4. 风险和异常</Text>{report.risks.map((value, index) => <View key={index}><Textarea className='text-area risk-input' value={value} onInput={event => updateList('risks', index, event.detail.value)} />{generatedReport?.risks[index]?.source_text && <Text className='source-text'>原话：{generatedReport.risks[index].source_text}</Text>}</View>)}<Button className='add-item' onClick={addRisk}>+ 添加风险或异常</Button></View>
    <View className='report-card card'><Text className='section-title'>5. 售后提醒</Text><Textarea className='text-area compact' value={report.afterSales} onInput={event => patch({ afterSales: event.detail.value })} />{generatedReport?.after_sales.map((item, index) => <Text className='source-text' key={index}>原话：{item.source_text}</Text>)}</View>

    {generatedReport && <View className='report-card card confirmation-card'><CheckboxGroup onChange={event => setReportConfirmed(event.detail.value.includes('confirmed'))}><View className='confirm-check'><Checkbox value='confirmed' checked={reportConfirmed} color='#173b65' /><Text>我已核对AI整理的材料、数量、单价和费用。</Text></View></CheckboxGroup></View>}
    <View className='fixed-actions'><Button className='secondary-btn' loading={saving} disabled={saving} onClick={saveDraft}>保存草稿</Button><Button className='primary-btn' disabled={saving || Boolean(generatedReport && !reportConfirmed)} onClick={sendAcceptance}>发给客户验收</Button></View>
  </View>
}

function Fee({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <View className='fee'><Text>{label}</Text><View className='fee-input'><Text>¥</Text><Input type='digit' value={value} placeholder='请填写费用' onInput={event => onChange(event.detail.value)} /></View></View>
}
