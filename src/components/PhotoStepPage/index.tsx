import Taro from '@tarojs/taro'
import { Button, View } from '@tarojs/components'
import { useState } from 'react'
import OrderSummary from '../OrderSummary'
import PhotoUploader from '../PhotoUploader'
import StepProgress from '../StepProgress'
import { useDelivery } from '../../context/DeliveryContext'
import { absoluteFileUrl } from '../../services/api'
import { deleteOrderPhoto, uploadOrderPhoto, type ApiPhoto } from '../../services/serviceOrders'

type PhotoPhase = 'before' | 'after'
type PhotoStepPageProps = {
  phase: PhotoPhase
  step: number
  label: string
  uploadedTitle: string
  missingTitle: string
  nextText: string
  nextUrl: string
}

export default function PhotoStepPage({
  phase,
  step,
  label,
  uploadedTitle,
  missingTitle,
  nextText,
  nextUrl
}: PhotoStepPageProps) {
  const delivery = useDelivery()
  const [uploading, setUploading] = useState(false)
  const [deletingIndex, setDeletingIndex] = useState<number | null>(null)
  const [failedPaths, setFailedPaths] = useState<string[]>([])
  const photos = phase === 'before' ? delivery.beforePhotos : delivery.afterPhotos
  const records = phase === 'before' ? delivery.beforePhotoRecords : delivery.afterPhotoRecords
  const setPhotos = phase === 'before' ? delivery.setBeforePhotos : delivery.setAfterPhotos
  const setRecords = phase === 'before' ? delivery.setBeforePhotoRecords : delivery.setAfterPhotoRecords
  const busy = uploading || deletingIndex !== null

  const upload = async (paths: string[]) => {
    if (!delivery.serviceOrderId) throw new Error('缺少服务单，请从工作台重新开始')
    if (uploading || !paths.length) return
    setUploading(true)
    const uploaded: ApiPhoto[] = []
    const failed: string[] = []
    try {
      for (const path of paths) {
        try {
          uploaded.push(await uploadOrderPhoto(delivery.serviceOrderId, phase, path))
        } catch {
          failed.push(path)
        }
      }
      if (uploaded.length) {
        setRecords([...records, ...uploaded])
        setPhotos([...photos, ...uploaded.map(photo => absoluteFileUrl(photo.file_url))])
      }
      setFailedPaths(current => [...new Set([...current.filter(path => !paths.includes(path)), ...failed])])
      if (failed.length) throw new Error(`${failed.length} 张照片上传失败，请点击重试`)
      Taro.showToast({ title: uploadedTitle, icon: 'success' })
    } finally {
      setUploading(false)
    }
  }

  const remove = async (index: number) => {
    if (!delivery.serviceOrderId) throw new Error('缺少服务单，请从工作台重新开始')
    if (busy) return
    const record = records[index]
    if (!record?.id) throw new Error('照片同步信息缺失，请返回工作台重新进入服务单')
    setDeletingIndex(index)
    try {
      await deleteOrderPhoto(delivery.serviceOrderId, record.id)
      setRecords(records.filter((_, itemIndex) => itemIndex !== index))
      setPhotos(photos.filter((_, itemIndex) => itemIndex !== index))
      Taro.showToast({ title: '照片已删除', icon: 'success' })
    } finally {
      setDeletingIndex(null)
    }
  }

  const next = () => {
    if (failedPaths.length) return Taro.showToast({ title: '请先重试上传失败的照片', icon: 'none' })
    if (busy) return Taro.showToast({ title: '照片正在同步，请稍候', icon: 'none' })
    return photos.length ? Taro.navigateTo({ url: nextUrl }) : Taro.showToast({ title: missingTitle, icon: 'none' })
  }

  return <View className='page'>
    <StepProgress current={step} />
    <OrderSummary compact />
    <PhotoUploader
      label={label}
      photos={photos}
      onAdd={upload}
      onRemove={remove}
      onRetry={() => upload([...failedPaths])}
      retryCount={failedPaths.length}
      loading={uploading}
      deletingIndex={deletingIndex}
    />
    <View className='fixed-actions'><Button className='primary-btn' disabled={busy || failedPaths.length > 0} onClick={next}>{nextText}</Button></View>
  </View>
}
