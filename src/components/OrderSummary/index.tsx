import { View, Text } from '@tarojs/components'
import { useDelivery } from '../../context/DeliveryContext'
import './index.scss'

export default function OrderSummary({ compact = false }: { compact?: boolean }) {
  const { remoteOrder } = useDelivery()
  if (!remoteOrder) {
    return <View className='order card'><Text className='order-line'>正在读取当前服务单...</Text></View>
  }
  return <View className='order card'>
    {!compact && <View className='order-head'><Text>{remoteOrder.order_no}</Text><Text className='status'>{remoteOrder.status === 'in_progress' ? '施工中' : remoteOrder.status}</Text></View>}
    <View className='order-main'><Text className='customer'>{remoteOrder.customer_name}</Text>{!compact && <Text className='phone'>{remoteOrder.customer_phone}</Text>}</View>
    <Text className='order-line'>地址：{remoteOrder.service_address}</Text>
    <Text className='order-line'>服务：{remoteOrder.service_type}</Text>
  </View>
}
