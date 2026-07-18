import Taro from '@tarojs/taro'
import { Button, Image, Text, View } from '@tarojs/components'
import './index.scss'

type PhotoUploaderProps = { label: string; photos: string[]; onChange: (v: string[]) => void; onAdd?: (paths: string[]) => Promise<void>; loading?: boolean }
export default function PhotoUploader({ label, photos, onChange, onAdd, loading = false }: PhotoUploaderProps) {
  const choose = async () => {
    try {
      const res = await Taro.chooseMedia({ count: 9 - photos.length, mediaType: ['image'], sourceType: ['album', 'camera'], sizeType: ['compressed'] })
      const paths = res.tempFiles.map(file => file.tempFilePath)
      if (onAdd) await onAdd(paths)
      else onChange([...photos, ...paths])
    } catch (error) {
      const message = (error as { errMsg?: string }).errMsg || ''
      if (!message.includes('cancel')) Taro.showToast({ title: message || '选择或上传照片失败', icon: 'none' })
    }
  }
  const preview = (current: string) => Taro.previewImage({ current, urls: photos })
  const remove = (index: number) => {
    Taro.showModal({ title: '删除照片', content: '确定删除这张照片吗？', success: res => res.confirm && onChange(photos.filter((_, i) => i !== index)) })
  }
  return <View>
    <Button className='photo-button' disabled={loading} loading={loading} onClick={choose}>📷 {loading ? '正在上传...' : label}</Button>
    <Text className='photo-tip'>可拍摄或从相册选择，最多 9 张</Text>
    <View className='photo-grid'>
      {photos.map((photo, index) => <View className='photo-item' key={photo}>
        <Image src={photo} mode='aspectFill' onClick={() => preview(photo)} />
        <View className='delete' onClick={() => remove(index)}>×</View>
      </View>)}
    </View>
    {photos.length > 0 && <Text className='photo-count'>已添加 {photos.length} 张照片</Text>}
  </View>
}
