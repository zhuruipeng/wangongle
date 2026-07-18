import Taro, { useDidShow } from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useState } from 'react'
import OrderSummary from '../../components/OrderSummary'
import { useDelivery } from '../../context/DeliveryContext'
import { serviceOrder } from '../../mock/service'
import { createServiceOrder, listServiceOrders } from '../../services/serviceOrders'
import './index.scss'

export default function Workbench() {
  const [date, setDate] = useState('')
  const [creating, setCreating] = useState(false)
  const { serviceOrderId, setServiceOrderId, setRemoteOrder } = useDelivery()
  useDidShow(() => setDate(new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })))
  const startDelivery = async () => {
    if (creating) return
    if (serviceOrderId) return Taro.navigateTo({ url: '/pages/before-photos/index' })
    setCreating(true)
    try {
      let order
      try {
        order = await createServiceOrder({ order_no: serviceOrder.orderNo, company_name: '安心空调服务', customer_name: serviceOrder.customer, customer_phone: serviceOrder.phone, service_address: serviceOrder.address, service_type: serviceOrder.service, technician_name: '张师傅', status: 'in_progress' })
      } catch (error) {
        const existing = (await listServiceOrders()).find(item => item.order_no === serviceOrder.orderNo)
        if (!existing) throw error
        order = existing
      }
      setServiceOrderId(order.id); setRemoteOrder(order)
      Taro.showToast({ title: '服务单已创建', icon: 'success' })
      await Taro.navigateTo({ url: '/pages/before-photos/index' })
    } catch (error) {
      Taro.showToast({ title: error instanceof Error ? error.message : '创建服务单失败', icon: 'none', duration: 3000 })
    } finally { setCreating(false) }
  }
  return <View className='page workbench'>
    <View className='brand'><Text className='page-title'>干完了</Text><Text className='slogan'>现场服务 AI 交付系统</Text></View>
    <View className='identity'><Text>当前公司：安心空调服务</Text><Text>当前师傅：张师傅</Text><Text>{date}</Text></View>
    <Button className='start-btn' loading={creating} disabled={creating} onClick={startDelivery}>{creating ? '正在创建服务单...' : '开始现场交付'}</Button>
    <View className='stats'>
      <View className='stat card'><Text className='number'>3</Text><Text>今日服务</Text></View>
      <View className='stat card'><Text className='number warning'>1</Text><Text>待客户验收</Text></View>
    </View>
    <View className='section-title'>最近服务单</View><OrderSummary />
  </View>
}
