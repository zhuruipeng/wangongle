import Taro from '@tarojs/taro'
import { Button, View } from '@tarojs/components'
import StepProgress from '../../components/StepProgress'
import OrderSummary from '../../components/OrderSummary'
import PhotoUploader from '../../components/PhotoUploader'
import { useDelivery } from '../../context/DeliveryContext'
import { uploadOrderPhoto } from '../../services/serviceOrders'
import { useState } from 'react'

export default function BeforePhotos() {
  const { serviceOrderId, beforePhotos, setBeforePhotos } = useDelivery()
  const [uploading, setUploading] = useState(false)
  const upload = async (paths: string[]) => {
    if (!serviceOrderId) throw new Error('缺少服务单，请从工作台重新开始')
    setUploading(true)
    try {
      for (const path of paths) await uploadOrderPhoto(serviceOrderId, 'before', path)
      setBeforePhotos([...beforePhotos, ...paths]); Taro.showToast({ title: '施工前照片已上传', icon: 'success' })
    } finally { setUploading(false) }
  }
  const next = () => beforePhotos.length ? Taro.navigateTo({ url: '/pages/after-photos/index' }) : Taro.showToast({ title: '请至少添加1张施工前照片', icon: 'none' })
  return <View className='page'><StepProgress current={0} /><OrderSummary compact /><PhotoUploader label='拍施工前照片' photos={beforePhotos} onChange={setBeforePhotos} onAdd={upload} loading={uploading} />
    <View className='fixed-actions'><Button className='primary-btn' disabled={uploading} onClick={next}>下一步：开始施工</Button></View>
  </View>
}
