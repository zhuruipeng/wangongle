import Taro from '@tarojs/taro'
import { Button, Image, Text, View } from '@tarojs/components'
import './index.scss'

type PhotoUploaderProps = {
  label: string
  photos: string[]
  onAdd: (paths: string[]) => Promise<void>
  onRemove: (index: number) => Promise<void>
  onRetry?: () => Promise<void>
  retryCount?: number
  loading?: boolean
  deletingIndex?: number | null
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : (error as { errMsg?: string })?.errMsg || '照片操作失败'
}

export default function PhotoUploader({
  label,
  photos,
  onAdd,
  onRemove,
  onRetry,
  retryCount = 0,
  loading = false,
  deletingIndex = null
}: PhotoUploaderProps) {
  const busy = loading || deletingIndex !== null
  const run = async (action: () => Promise<void>) => {
    try {
      await action()
    } catch (error) {
      const message = errorMessage(error)
      if (!message.includes('cancel')) Taro.showToast({ title: message, icon: 'none', duration: 3000 })
    }
  }
  const choose = async () => {
    try {
      const res = await Taro.chooseMedia({ count: 9 - photos.length, mediaType: ['image'], sourceType: ['album', 'camera'], sizeType: ['compressed'] })
      const paths = res.tempFiles.map(file => file.tempFilePath)
      await onAdd(paths)
    } catch (error) {
      const message = errorMessage(error)
      if (!message.includes('cancel')) Taro.showToast({ title: message || '选择或上传照片失败', icon: 'none' })
    }
  }
  const preview = (current: string) => Taro.previewImage({ current, urls: photos })
  const remove = (index: number) => {
    if (busy) return
    Taro.showModal({
      title: '删除照片',
      content: '确定删除这张照片吗？删除后服务器文件也会移除。',
      success: res => {
        if (res.confirm) void run(() => onRemove(index))
      }
    })
  }
  return <View>
    <Button className='photo-button' disabled={busy || retryCount > 0 || photos.length >= 9} loading={loading} onClick={choose}>
      📷 {loading ? '正在上传...' : retryCount > 0 ? '请先处理上传失败照片' : photos.length >= 9 ? '已达到 9 张上限' : label}
    </Button>
    <Text className='photo-tip'>可拍摄或从相册选择，最多 9 张</Text>
    {retryCount > 0 && onRetry && <Button className='photo-retry' disabled={busy} loading={loading} onClick={() => run(onRetry)}>重试失败照片（{retryCount}）</Button>}
    <View className='photo-grid'>
      {photos.map((photo, index) => <View className='photo-item' key={photo}>
        <Image src={photo} mode='aspectFill' onClick={() => preview(photo)} />
        <View className={`delete ${deletingIndex === index ? 'deleting' : ''}`} onClick={() => remove(index)}>{deletingIndex === index ? '…' : '×'}</View>
      </View>)}
    </View>
    {photos.length > 0 && <Text className='photo-count'>已添加 {photos.length} 张照片</Text>}
  </View>
}
