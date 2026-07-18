import { View, Text } from '@tarojs/components'
import './index.scss'

const steps = ['施工前', '施工后', '说一句', '确认报告']
export default function StepProgress({ current }: { current: number }) {
  return <View className='steps'>
    {steps.map((step, index) => <View className={`step ${index < current ? 'done' : ''} ${index === current ? 'active' : ''}`} key={step}>
      <View className='step-dot'>{index < current ? '✓' : index + 1}</View>
      <Text>{step}</Text>
    </View>)}
  </View>
}
