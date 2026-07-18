import Taro, { getCurrentInstance, useLoad } from '@tarojs/taro'
import { Button, Checkbox, CheckboxGroup, Image, Text, View } from '@tarojs/components'
import { useState } from 'react'
import SignaturePad from '../../components/SignaturePad'
import { useDelivery } from '../../context/DeliveryContext'
import { initialReport, serviceOrder } from '../../mock/service'
import { absoluteFileUrl } from '../../services/api'
import { getServiceOrder } from '../../services/serviceOrders'
import './index.scss'

const money = (value: string) => Number(value) || 0

export default function CustomerAcceptance() {
  const delivery = useDelivery()
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [completedAt, setCompletedAt] = useState('')
  const [accepted, setAccepted] = useState(false)
  const [signed, setSigned] = useState(false)
  const [finishedAt, setFinishedAt] = useState('')
  useLoad(() => {
    setCompletedAt(formatTime(new Date()))
    const queryId = getCurrentInstance().router?.params?.serviceOrderId
    const id = queryId || delivery.serviceOrderId
    if (!id) return
    delivery.setServiceOrderId(id); setLoading(true); setLoadError('')
    getServiceOrder(id)
      .then(order => delivery.setRemoteOrder(order))
      .catch(error => setLoadError(error instanceof Error ? error.message : '服务单加载失败'))
      .finally(() => setLoading(false))
  })

  const remote = delivery.remoteOrder
  const report = remote?.report ? {
    completed: remote.report.completed_items,
    materials: remote.report.materials.map(item => ({ name: item.name, quantity: item.quantity, price: item.amount_cents === null ? '' : String(item.amount_cents / 100) })),
    serviceFee: String((remote.report.fee_items.find(item => item.name === '安装服务费')?.amount_cents || 0) / 100),
    materialFee: String((remote.report.fee_items.find(item => item.name === '材料费')?.amount_cents || 0) / 100),
    paid: String(remote.report.paid_amount_cents / 100), risks: remote.report.risks,
    afterSales: remote.report.after_sales_reminder
  } : delivery.report || initialReport
  const orderInfo = remote ? { orderNo: remote.order_no, customer: remote.customer_name, address: remote.service_address, service: remote.service_type, technician: remote.technician_name, company: remote.company_name } : { ...serviceOrder, technician: '张师傅', company: '安心空调服务' }
  const beforePhotos = remote ? remote.before_photos.map(item => absoluteFileUrl(item.file_url)) : delivery.beforePhotos
  const afterPhotos = remote ? remote.after_photos.map(item => absoluteFileUrl(item.file_url)) : delivery.afterPhotos

  const total = money(report.serviceFee) + money(report.materialFee)
  const due = Math.max(0, total - money(report.paid))
  const finished = Boolean(finishedAt)
  const confirm = () => {
    if (!accepted) return Taro.showToast({ title: '请先勾选客户确认说明', icon: 'none' })
    if (!signed) return Taro.showToast({ title: '请先完成手写签名', icon: 'none' })
    const time = formatTime(new Date())
    setFinishedAt(time)
    Taro.showModal({ title: '验收成功', content: '感谢您的确认，本次服务已完成验收。', showCancel: false })
  }

  return <View className='acceptance-page'>
    <View className={`acceptance-header ${finished ? 'finished' : ''}`}>
      <Text className='acceptance-brand'>干完了</Text><Text className='company'>{orderInfo.company}</Text>
      <Text className='acceptance-status'>{finished ? '✓ 服务已验收' : '状态：等待客户验收'}</Text>
      <Text className='order-number'>服务单号：{orderInfo.orderNo}</Text>
      {finished && <Text className='finish-time'>确认时间：{finishedAt}</Text>}
    </View>

    <Section title='客户和服务信息'>
      {loading && <Text className='load-note'>正在读取服务单...</Text>}{loadError && <Text className='load-error'>{loadError}，当前显示模拟数据。</Text>}
      <Info label='客户' value={orderInfo.customer} /><Info label='服务地址' value={orderInfo.address} />
      <Info label='服务项目' value={orderInfo.service} /><Info label='服务师傅' value={orderInfo.technician} />
      <Info label='完工时间' value={completedAt || '正在获取时间'} />
    </Section>

    <Section title='施工前后照片'>
      <PhotoArea title='施工前' photos={beforePhotos} />
      <PhotoArea title='施工后' photos={afterPhotos} />
    </Section>

    <Section title='完成内容'>
      {report.completed.map((item, index) => <View className='check-line' key={index}><Text className='check-icon'>✓</Text><Text>{item}</Text></View>)}
    </Section>

    <Section title='使用材料'>
      {report.materials.map((item, index) => <View className='material-line' key={index}><View><Text className='material-title'>{item.name}</Text><Text className='material-quantity'>{item.quantity}</Text></View><Text className='material-price'>{item.price}元</Text></View>)}
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
      <CheckboxGroup onChange={event => !finished && setAccepted(event.detail.value.includes('accepted'))}>
        <View className={`confirm-check ${finished ? 'disabled' : ''}`}>
          <Checkbox value='accepted' checked={accepted} disabled={finished} color='#173b65' />
          <Text>我已查看施工内容、材料及费用，并确认本次服务已经完成。</Text>
        </View>
      </CheckboxGroup>
      <Text className='signature-title'>客户手写签名</Text>
      <SignaturePad signed={signed} disabled={finished} onSignedChange={setSigned} />
    </Section>

    {finished && <View className='success-message'>✓ 感谢您的确认，本次服务已完成验收。</View>}
    <View className='acceptance-fixed'><Button className='primary-btn' disabled={finished} onClick={confirm}>{finished ? '验收已完成' : '确认验收'}</Button></View>
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
