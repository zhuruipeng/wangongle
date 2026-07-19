import Taro, { getCurrentInstance, useLoad } from '@tarojs/taro'
import { Button, Checkbox, CheckboxGroup, Image, Text, View } from '@tarojs/components'
import { useState } from 'react'
import SignaturePad from '../../components/SignaturePad'
import { useDelivery } from '../../context/DeliveryContext'
import { absoluteFileUrl } from '../../services/api'
import { acceptServiceOrder, getServiceOrder, type ApiServiceOrder } from '../../services/serviceOrders'
import './index.scss'

const money = (value: string) => Number(value) || 0
type AcceptanceReport = {
  completed: string[]
  materials: Array<{ name: string; quantity: string; price: string }>
  serviceFee: string
  materialFee: string
  paid: string
  risks: string[]
  afterSales: string
}

const emptyReport: AcceptanceReport = {
  completed: [],
  materials: [],
  serviceFee: '0',
  materialFee: '0',
  paid: '0',
  risks: [],
  afterSales: ''
}

function reportFromOrder(order: ApiServiceOrder | null): AcceptanceReport {
  if (!order) return emptyReport
  if (order.report) {
    return {
      completed: order.report.completed_items,
      materials: order.report.materials.map(item => ({
        name: item.name,
        quantity: item.quantity,
        price: item.amount_cents === null ? '' : String(item.amount_cents / 100)
      })),
      serviceFee: String((order.report.fee_items.find(item => item.name === '安装服务费')?.amount_cents || 0) / 100),
      materialFee: String((order.report.fee_items.find(item => item.name === '材料费')?.amount_cents || 0) / 100),
      paid: String(order.report.paid_amount_cents / 100),
      risks: order.report.risks,
      afterSales: order.report.after_sales_reminder
    }
  }
  if (!order.ai_report) return emptyReport
  const materialFee = order.ai_report.materials.reduce((sum, item) => sum + (item.amount_cents.value || 0), 0)
  const serviceFee = order.ai_report.labor.reduce((sum, item) => sum + (item.amount_cents.value || 0), 0)
  return {
    completed: order.ai_report.completed_items.map(item => item.content).filter(Boolean),
    materials: order.ai_report.materials.map(item => ({
      name: item.name.value || '待确认材料',
      quantity: item.quantity.value || '待确认',
      price: item.amount_cents.value === null ? '' : String(item.amount_cents.value / 100)
    })),
    serviceFee: String(serviceFee / 100),
    materialFee: String(materialFee / 100),
    paid: String(order.paid_amount_cents / 100),
    risks: [...order.ai_report.risks, ...order.ai_report.exceptions],
    afterSales: order.ai_report.customer_confirmation_text || ''
  }
}

export default function CustomerAcceptance() {
  const delivery = useDelivery()
  const [orderId, setOrderId] = useState('')
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [completedAt, setCompletedAt] = useState('')
  const [accepted, setAccepted] = useState(false)
  const [signed, setSigned] = useState(false)
  const [finishedAt, setFinishedAt] = useState('')
  useLoad(() => {
    setCompletedAt(formatTime(new Date()))
    const queryId = getCurrentInstance().router?.params?.serviceOrderId
    const id = queryId || delivery.serviceOrderId
    if (!id) {
      setLoadError('缺少服务单，请让师傅重新提交验收')
      return
    }
    setOrderId(id)
    delivery.setServiceOrderId(id); setLoading(true); setLoadError('')
    getServiceOrder(id)
      .then(order => delivery.selectServiceOrder(order))
      .catch(error => setLoadError(error instanceof Error ? error.message : '服务单加载失败'))
      .finally(() => setLoading(false))
  })

  const remote = delivery.remoteOrder
  const report = reportFromOrder(remote)
  const orderInfo = remote
    ? { orderNo: remote.order_no, customer: remote.customer_name, address: remote.service_address, service: remote.service_type, technician: remote.technician_name, company: remote.company_name }
    : { orderNo: '--', customer: '--', address: '--', service: '--', technician: '--', company: '干完了' }
  const beforePhotos = remote ? remote.before_photos.map(item => absoluteFileUrl(item.file_url)) : delivery.beforePhotos
  const afterPhotos = remote ? remote.after_photos.map(item => absoluteFileUrl(item.file_url)) : delivery.afterPhotos

  const total = money(report.serviceFee) + money(report.materialFee)
  const due = Math.max(0, total - money(report.paid))
  const finished = remote?.status === 'accepted' || Boolean(finishedAt)
  const confirm = async () => {
    if (submitting || finished) return
    if (!orderId || !remote || loadError) return Taro.showToast({ title: '服务单尚未加载完成', icon: 'none' })
    if (!accepted) return Taro.showToast({ title: '请先勾选客户确认说明', icon: 'none' })
    if (!signed) return Taro.showToast({ title: '请先完成手写签名', icon: 'none' })
    setSubmitting(true)
    try {
      const exported = await Taro.canvasToTempFilePath({ canvasId: 'customerSignature', fileType: 'png', quality: 1 })
      if (!exported.tempFilePath) throw new Error('签名图片生成失败，请重新签名')
      const result = await acceptServiceOrder(orderId, exported.tempFilePath)
      const acceptedAt = new Date(result.acceptance.accepted_at)
      setFinishedAt(formatTime(Number.isNaN(acceptedAt.getTime()) ? new Date() : acceptedAt))
      delivery.setRemoteOrder({ ...remote, status: 'accepted' })
      await Taro.showModal({ title: '验收成功', content: '感谢您的确认，本次服务已完成验收。', showCancel: false })
    } catch (error) {
      Taro.showToast({ title: error instanceof Error ? error.message : '验收提交失败，请重试', icon: 'none', duration: 3000 })
    } finally {
      setSubmitting(false)
    }
  }
  const handlePrimaryAction = () => {
    if (finished) return Taro.reLaunch({ url: '/pages/workbench/index' })
    return confirm()
  }

  return <View className='acceptance-page'>
    <View className={`acceptance-header ${finished ? 'finished' : ''}`}>
      <Text className='acceptance-brand'>干完了</Text><Text className='company'>{orderInfo.company}</Text>
      <Text className='acceptance-status'>{finished ? '✓ 服务已验收' : '状态：等待客户验收'}</Text>
      <Text className='order-number'>服务单号：{orderInfo.orderNo}</Text>
      {finished && finishedAt && <Text className='finish-time'>确认时间：{finishedAt}</Text>}
    </View>

    <Section title='客户和服务信息'>
      {loading && <Text className='load-note'>正在读取服务单...</Text>}{loadError && <Text className='load-error'>{loadError}</Text>}
      <Info label='客户' value={orderInfo.customer} /><Info label='服务地址' value={orderInfo.address} />
      <Info label='服务项目' value={orderInfo.service} /><Info label='服务师傅' value={orderInfo.technician} />
      <Info label='完工时间' value={completedAt || '正在获取时间'} />
    </Section>

    <Section title='施工前后照片'>
      <PhotoArea title='施工前' photos={beforePhotos} />
      <PhotoArea title='施工后' photos={afterPhotos} />
    </Section>

    <Section title='完成内容'>
      {report.completed.length ? report.completed.map((item, index) => <View className='check-line' key={index}><Text className='check-icon'>✓</Text><Text>{item}</Text></View>) : <Text className='empty-note'>暂无完成内容</Text>}
    </Section>

    <Section title='使用材料'>
      {report.materials.length ? report.materials.map((item, index) => <View className='material-line' key={index}><View><Text className='material-title'>{item.name}</Text><Text className='material-quantity'>{item.quantity}</Text></View><Text className='material-price'>{item.price ? `${item.price}元` : '金额待确认'}</Text></View>) : <Text className='empty-note'>本次服务未记录材料</Text>}
    </Section>

    <Section title='工时及费用'>
      <PriceLine label='安装服务费' value={money(report.serviceFee)} /><PriceLine label='材料费' value={money(report.materialFee)} />
      <View className='price-highlight'><Text>合计</Text><Text>¥{total}</Text></View>
      <PriceLine label='已收' value={money(report.paid)} />
      <View className='price-highlight due'><Text>待收</Text><Text>¥{due}</Text></View>
    </Section>

    <View className='acceptance-card risk-card'><Text className='acceptance-section-title'>风险和异常</Text>
      {report.risks.length ? report.risks.map((item, index) => <Text className='risk-line' key={index}>• {item}</Text>) : <Text className='risk-line'>本次服务未记录异常。</Text>}
    </View>

    <Section title='客户确认'>
      <CheckboxGroup onChange={event => !finished && !submitting && setAccepted(event.detail.value.includes('accepted'))}>
        <View className={`confirm-check ${finished ? 'disabled' : ''}`}>
          <Checkbox value='accepted' checked={accepted} disabled={finished || submitting || loading || !remote} color='#173b65' />
          <Text>我已查看施工内容、材料及费用，并确认本次服务已经完成。</Text>
        </View>
      </CheckboxGroup>
      <Text className='signature-title'>客户手写签名</Text>
      <SignaturePad signed={signed} disabled={finished || submitting || loading || !remote} onSignedChange={setSigned} />
    </Section>

    {finished && <View className='success-message'>✓ 感谢您的确认，本次服务已完成验收。</View>}
    <View className='acceptance-fixed'><Button className='primary-btn' loading={submitting} disabled={!finished && (submitting || loading || !remote)} onClick={handlePrimaryAction}>{finished ? '返回工作台' : submitting ? '正在提交验收' : '确认验收'}</Button></View>
  </View>
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <View className='acceptance-card'><Text className='acceptance-section-title'>{title}</Text>{children}</View>
}
function Info({ label, value }: { label: string; value: string }) { return <View className='info-line'><Text>{label}</Text><Text>{value}</Text></View> }
function PriceLine({ label, value }: { label: string; value: number }) { return <View className='price-line'><Text>{label}</Text><Text>{value}元</Text></View> }
function PhotoArea({ title, photos }: { title: string; photos: string[] }) {
  return <View className='photo-area'><Text className='photo-area-title'>{title}</Text>
    {photos.length ? <View className='acceptance-photos'>{photos.map(photo => <Image key={photo} src={photo} mode='aspectFill' onClick={() => Taro.previewImage({ current: photo, urls: photos })} />)}</View> : <View className='photo-empty'>暂无{title}照片</View>}
  </View>
}
function formatTime(date: Date) {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
