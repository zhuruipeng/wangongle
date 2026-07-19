import Taro, { useDidShow } from '@tarojs/taro'
import { Button, Input, Text, View } from '@tarojs/components'
import { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { useDelivery } from '../../context/DeliveryContext'
import { createServiceOrder, listServiceOrders, type ApiServiceOrder } from '../../services/serviceOrders'
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

const emptyDraft: OrderDraft = {
  companyName: '',
  customerName: '',
  customerPhone: '',
  serviceAddress: '',
  serviceType: ''
}

export default function Workbench() {
  const [date, setDate] = useState('')
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState<OrderDraft>(emptyDraft)
  const [recentOrders, setRecentOrders] = useState<ApiServiceOrder[]>([])
  const [listError, setListError] = useState('')
  const { user } = useAuth()
  const { setServiceOrderId, setRemoteOrder } = useDelivery()
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
        service_type: values.serviceType,
        status: 'in_progress'
      })
      setServiceOrderId(order.id); setRemoteOrder(order)
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
      <Field label='服务地址'><Input value={draft.serviceAddress} maxlength={500} placeholder='请输入上门服务地址' onInput={event => updateDraft('serviceAddress', event.detail.value)} /></Field>
      <Field label='服务项目'><Input value={draft.serviceType} maxlength={300} placeholder='例如：1.5匹壁挂空调安装' onInput={event => updateDraft('serviceType', event.detail.value)} /></Field>
      <Button className='start-btn' loading={creating} disabled={creating} onClick={startDelivery}>{creating ? '正在创建服务单' : '创建并开始交付'}</Button>
    </View>
    <View className='stats'>
      <View className='stat card'><Text className='number'>{recentOrders.length}</Text><Text>我的服务单</Text></View>
      <View className='stat card'><Text className='number warning'>{recentOrders.filter(order => order.status === 'waiting_acceptance').length}</Text><Text>待客户验收</Text></View>
    </View>
    <View className='section-title'>最近服务单</View>
    {!!listError && <View className='order-list-message card'><Text>{listError}</Text></View>}
    {!listError && recentOrders.length === 0 && <View className='order-list-message card'><Text>还没有服务单，点击上方按钮开始第一单。</Text></View>}
    {recentOrders.map(order => <View className='workbench-order card' key={order.id}>
      <View className='workbench-order-head'><Text>{order.order_no}</Text><Text className='workbench-order-status'>{order.status === 'waiting_acceptance' ? '待验收' : order.status === 'accepted' ? '已完成' : '进行中'}</Text></View>
      <Text className='workbench-order-customer'>{order.customer_name}</Text>
      <Text className='workbench-order-line'>{order.service_address}</Text>
      <Text className='workbench-order-line'>{order.service_type}</Text>
      {order.ai_report?.work_summary && <Text className='workbench-order-line'>报告：{order.ai_report.work_summary}</Text>}
    </View>)}
  </View>
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <View className='workbench-field'><Text>{label}</Text>{children}</View>
}
