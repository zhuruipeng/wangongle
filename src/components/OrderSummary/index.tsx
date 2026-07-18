import { View, Text } from '@tarojs/components'
import { serviceOrder } from '../../mock/service'
import './index.scss'

export default function OrderSummary({ compact = false }: { compact?: boolean }) {
  return <View className='order card'>
    {!compact && <View className='order-head'><Text>{serviceOrder.orderNo}</Text><Text className='status'>{serviceOrder.status}</Text></View>}
    <View className='order-main'><Text className='customer'>{serviceOrder.customer}</Text>{!compact && <Text className='phone'>{serviceOrder.phone}</Text>}</View>
    <Text className='order-line'>📍 {serviceOrder.address}</Text>
    <Text className='order-line'>🔧 {serviceOrder.service}</Text>
  </View>
}
