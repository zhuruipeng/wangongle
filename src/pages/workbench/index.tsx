import Taro, { useDidShow } from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { useDelivery } from '../../context/DeliveryContext'
import { serviceOrder } from '../../mock/service'
import { createServiceOrder, listServiceOrders, type ApiServiceOrder } from '../../services/serviceOrders'
import './index.scss'

function createOrderNumber(): string {
  const randomSuffix = Math.random().toString(36).slice(2, 8).toUpperCase() || '000000'
  return `GW-${Date.now()}-${randomSuffix}`
}

export default function Workbench() {
  const [date, setDate] = useState('')
  const [creating, setCreating] = useState(false)
  const [recentOrders, setRecentOrders] = useState<ApiServiceOrder[]>([])
  const [listError, setListError] = useState('')
  const { user } = useAuth()
  const { serviceOrderId, setServiceOrderId, setRemoteOrder } = useDelivery()
  useDidShow(async () => {
    setDate(new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' }))
    try {
      setRecentOrders(await listServiceOrders())
      setListError('')
    } catch (error) {
      setListError(error instanceof Error ? error.message : '服务单加载失败')
    }
  })
  const startDelivery = async () => {
    if (creating) return
    if (serviceOrderId) return Taro.navigateTo({ url: '/pages/before-photos/index' })
    setCreating(true)
    try {
      const order = await createServiceOrder({ order_no: createOrderNumber(), company_name: '安心空调服务', customer_name: serviceOrder.customer, customer_phone: serviceOrder.phone, service_address: serviceOrder.address, service_type: serviceOrder.service, status: 'in_progress' })
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
    <View className='identity'><Text>当前公司：安心空调服务</Text><Text>当前师傅：{user?.technician_name || '资料待完善'}</Text><Text>{date}</Text></View>
    <Button className='start-btn' loading={creating} disabled={creating} onClick={startDelivery}>{creating ? '正在创建服务单...' : '开始现场交付'}</Button>
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
    </View>)}
  </View>
}
