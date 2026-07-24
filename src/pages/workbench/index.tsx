import Taro, { useDidShow } from '@tarojs/taro'
import { Button, Input, Text, View } from '@tarojs/components'
import { useMemo, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { useDelivery } from '../../context/DeliveryContext'
import {
  createServiceOrder,
  downloadOrderPdf,
  listServiceOrders,
  type ApiServiceOrder
} from '../../services/serviceOrders'
import './index.scss'

function createOrderNumber(): string {
  const randomSuffix = Math.random().toString(36).slice(2, 8).toUpperCase() || '000000'
  return `GW-${Date.now()}-${randomSuffix}`
}

type OrderDraft = {
  companyName: string
  customerName: string
  customerPhone: string
  serviceAddress: string
  serviceType: string
}

type SelectedLocation = {
  name: string
  latitude: number
  longitude: number
}

const emptyDraft: OrderDraft = {
  companyName: '',
  customerName: '',
  customerPhone: '',
  serviceAddress: '',
  serviceType: ''
}

function orderStatusLabel(order: ApiServiceOrder): string {
  if (order.status === 'waiting_acceptance') return '待验收'
  if (order.status === 'accepted') return '已完成'
  if (order.status === 'cancelled') return '已取消'
  if (order.status === 'draft') return '草稿'
  return '进行中'
}

function orderActionLabel(order: ApiServiceOrder): string {
  if (order.status === 'waiting_acceptance') return '客户验收'
  if (order.status === 'accepted') return '查看验收'
  if (order.status === 'cancelled') return '已取消'
  return '继续交付'
}

function nextOrderPage(order: ApiServiceOrder): string {
  if (order.status === 'waiting_acceptance' || order.status === 'accepted') {
    return `/pages/customer-acceptance/index?serviceOrderId=${order.id}`
  }
  if (!order.before_photos.length) return '/pages/before-photos/index'
  if (!order.after_photos.length) return '/pages/after-photos/index'
  if (!order.transcript) return '/pages/voice/index'
  return '/pages/report/index'
}

function matchesOrder(order: ApiServiceOrder, query: string): boolean {
  const keyword = query.trim().toLocaleLowerCase()
  if (!keyword) return true
  return [
    order.order_no,
    order.company_name,
    order.customer_name,
    order.customer_phone,
    order.service_address,
    order.service_type,
    order.technician_name,
    orderStatusLabel(order)
  ].some(value => value.toLocaleLowerCase().includes(keyword))
}

export default function Workbench() {
  const [date, setDate] = useState('')
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState<OrderDraft>(emptyDraft)
  const [recentOrders, setRecentOrders] = useState<ApiServiceOrder[]>([])
  const [listError, setListError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [choosingLocation, setChoosingLocation] = useState(false)
  const [selectedLocation, setSelectedLocation] = useState<SelectedLocation | null>(null)
  const [openingPdfId, setOpeningPdfId] = useState('')
  const { user } = useAuth()
  const { selectServiceOrder } = useDelivery()
  const visibleOrders = useMemo(() => recentOrders.filter(order => matchesOrder(order, searchQuery)), [recentOrders, searchQuery])
  useDidShow(async () => {
    setDate(new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' }))
    try {
      setRecentOrders(await listServiceOrders())
      setListError('')
    } catch (error) {
      setListError(error instanceof Error ? error.message : '服务单加载失败')
    }
  })
  const updateDraft = (key: keyof OrderDraft, value: string) => setDraft(current => ({ ...current, [key]: value }))
  const updateServiceAddress = (value: string) => {
    setSelectedLocation(null)
    updateDraft('serviceAddress', value)
  }
  const chooseServiceLocation = async () => {
    if (choosingLocation) return
    setChoosingLocation(true)
    try {
      const result = await Taro.chooseLocation({})
      const name = result.name.trim()
      const address = result.address.trim()
      const fullAddress = name && !address.includes(name) ? `${address} ${name}`.trim() : (address || name)
      setSelectedLocation({
        name,
        latitude: result.latitude,
        longitude: result.longitude
      })
      updateDraft('serviceAddress', fullAddress)
    } catch (error) {
      const errMsg = (error as { errMsg?: string })?.errMsg || (error instanceof Error ? error.message : '')
      if (!/cancel/i.test(errMsg)) {
        const denied = /auth|deny|permission|privacy/i.test(errMsg)
        Taro.showToast({
          title: denied ? '请允许使用位置信息后重试' : '地图选址失败，请重试',
          icon: 'none'
        })
      }
    } finally {
      setChoosingLocation(false)
    }
  }
  const openOrder = async (order: ApiServiceOrder) => {
    if (order.status === 'cancelled') return
    selectServiceOrder(order)
    await Taro.navigateTo({ url: nextOrderPage(order) })
  }
  const openOrderLocation = async (order: ApiServiceOrder) => {
    if (order.service_latitude == null || order.service_longitude == null) return
    await Taro.openLocation({
      latitude: order.service_latitude,
      longitude: order.service_longitude,
      name: order.service_location_name || order.customer_name,
      address: order.service_address,
      scale: 18
    })
  }
  const openOrderPdf = async (order: ApiServiceOrder) => {
    if (openingPdfId) return
    setOpeningPdfId(order.id)
    try {
      const filePath = await downloadOrderPdf(order.id)
      await Taro.openDocument({ filePath, fileType: 'pdf', showMenu: true })
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : 'PDF打开失败，请重试',
        icon: 'none'
      })
    } finally {
      setOpeningPdfId('')
    }
  }
  const startDelivery = async () => {
    if (creating) return
    const values = Object.fromEntries(Object.entries(draft).map(([key, value]) => [key, value.trim()])) as OrderDraft
    if (Object.values(values).some(value => !value)) {
      return Taro.showToast({ title: '请完整填写服务单资料', icon: 'none' })
    }
    setCreating(true)
    try {
      const order = await createServiceOrder({
        order_no: createOrderNumber(),
        company_name: values.companyName,
        customer_name: values.customerName,
        customer_phone: values.customerPhone,
        service_address: values.serviceAddress,
        ...(selectedLocation ? {
          service_location_name: selectedLocation.name,
          service_latitude: selectedLocation.latitude,
          service_longitude: selectedLocation.longitude
        } : {}),
        service_type: values.serviceType,
        status: 'in_progress'
      })
      selectServiceOrder(order)
      setRecentOrders(current => [order, ...current.filter(item => item.id !== order.id)])
      Taro.showToast({ title: '服务单已创建', icon: 'success' })
      await Taro.navigateTo({ url: '/pages/before-photos/index' })
    } catch (error) {
      Taro.showToast({ title: error instanceof Error ? error.message : '创建服务单失败', icon: 'none', duration: 3000 })
    } finally { setCreating(false) }
  }
  return <View className='page workbench'>
    <View className='brand'><Text className='page-title'>干完了</Text><Text className='slogan'>现场服务 AI 交付系统</Text></View>
    <View className='identity'><Text>当前师傅：{user?.technician_name || '资料待完善'}</Text><Text>{date}</Text></View>
    <View className='order-form card'>
      <Text className='section-title'>新建服务单</Text>
      <Field label='服务公司'><Input value={draft.companyName} maxlength={200} placeholder='请输入公司或门店名称' onInput={event => updateDraft('companyName', event.detail.value)} /></Field>
      <Field label='客户姓名'><Input value={draft.customerName} maxlength={100} placeholder='请输入客户姓名' onInput={event => updateDraft('customerName', event.detail.value)} /></Field>
      <Field label='联系电话'><Input value={draft.customerPhone} maxlength={50} type='number' placeholder='请输入客户联系电话' onInput={event => updateDraft('customerPhone', event.detail.value)} /></Field>
      <Field label='服务地址'>
        <View className='address-input-row'>
          <Input
            value={draft.serviceAddress}
            maxlength={500}
            placeholder='请输入地址或使用地图选址'
            onInput={event => updateServiceAddress(event.detail.value)}
          />
          <Button className='location-btn' loading={choosingLocation} disabled={choosingLocation} onClick={chooseServiceLocation}>地图选址</Button>
        </View>
        {selectedLocation && <Text className='location-selected'>已定位：{selectedLocation.latitude.toFixed(6)}, {selectedLocation.longitude.toFixed(6)}</Text>}
      </Field>
      <Field label='服务项目'><Input value={draft.serviceType} maxlength={300} placeholder='例如：1.5匹壁挂空调安装' onInput={event => updateDraft('serviceType', event.detail.value)} /></Field>
      <Button className='start-btn' loading={creating} disabled={creating} onClick={startDelivery}>{creating ? '正在创建服务单' : '创建并开始交付'}</Button>
    </View>
    <View className='stats'>
      <View className='stat card'><Text className='number'>{recentOrders.length}</Text><Text>我的服务单</Text></View>
      <View className='stat card'><Text className='number warning'>{recentOrders.filter(order => order.status === 'waiting_acceptance').length}</Text><Text>待客户验收</Text></View>
    </View>
    <View className='recent-orders-head'>
      <Text className='section-title'>最近服务单</Text>
      {!!searchQuery.trim() && <Text className='search-result-count'>{visibleOrders.length} 条匹配</Text>}
    </View>
    <View className='order-search'>
      <Input
        value={searchQuery}
        confirmType='search'
        maxlength={100}
        placeholder='搜索服务单号、客户、电话、地址或服务项目'
        onInput={event => setSearchQuery(event.detail.value)}
      />
      {!!searchQuery && <Button className='order-search-clear' onClick={() => setSearchQuery('')}>×</Button>}
    </View>
    {!!listError && <View className='order-list-message card'><Text>{listError}</Text></View>}
    {!listError && recentOrders.length === 0 && <View className='order-list-message card'><Text>还没有服务单，点击上方按钮开始第一单。</Text></View>}
    {!listError && recentOrders.length > 0 && visibleOrders.length === 0 && <View className='order-list-message card'><Text>没有找到匹配的服务单，请更换关键词。</Text></View>}
    {visibleOrders.map(order => <View className='workbench-order card' key={order.id}>
      <View className='workbench-order-head'><Text>{order.order_no}</Text><Text className={`workbench-order-status status-${order.status}`}>{orderStatusLabel(order)}</Text></View>
      <Text className='workbench-order-customer'>{order.customer_name}</Text>
      <Text className='workbench-order-line'>{order.customer_phone}</Text>
      <Text className='workbench-order-line'>{order.service_address}</Text>
      {order.service_latitude != null && order.service_longitude != null && <Text className='workbench-order-location'>已保存精确定位</Text>}
      <Text className='workbench-order-line'>{order.service_type}</Text>
      {order.ai_report?.work_summary && <Text className='workbench-order-line'>报告：{order.ai_report.work_summary}</Text>}
      <Button className='workbench-order-action' disabled={order.status === 'cancelled'} onClick={() => openOrder(order)}>{orderActionLabel(order)}</Button>
      <View className='workbench-order-secondary-actions'>
        {order.service_latitude != null && order.service_longitude != null &&
          <Button className='workbench-order-secondary' onClick={() => openOrderLocation(order)}>地图导航</Button>}
        {(order.report || order.generated_report || order.ai_report) &&
          <Button className='workbench-order-secondary pdf' loading={openingPdfId === order.id} disabled={Boolean(openingPdfId)} onClick={() => openOrderPdf(order)}>查看 PDF</Button>}
      </View>
    </View>)}
  </View>
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <View className='workbench-field'><Text>{label}</Text>{children}</View>
}
