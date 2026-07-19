import Taro from '@tarojs/taro'
import { act, create } from 'react-test-renderer'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDelivery } from '../../context/DeliveryContext'
import { deleteOrderPhoto, uploadOrderPhoto, type ApiPhoto } from '../../services/serviceOrders'
import PhotoStepPage from './index'

type CapturedUploaderProps = {
  onAdd: (paths: string[]) => Promise<void>
  onRemove: (index: number) => Promise<void>
  onRetry: () => Promise<void>
  retryCount: number
}

const uploaderMock = vi.hoisted(() => ({ props: null as CapturedUploaderProps | null }))
const uploaderProps = () => {
  if (!uploaderMock.props) throw new Error('PhotoUploader has not rendered')
  return uploaderMock.props
}

vi.mock('@tarojs/taro', () => ({
  default: { navigateTo: vi.fn(), showToast: vi.fn() }
}))
vi.mock('@tarojs/components', () => ({ Button: 'button', View: 'view' }))
vi.mock('../OrderSummary', () => ({ default: () => null }))
vi.mock('../StepProgress', () => ({ default: () => null }))
vi.mock('../PhotoUploader', () => ({ default: (props: CapturedUploaderProps) => { uploaderMock.props = props; return null } }))
vi.mock('../../context/DeliveryContext', () => ({ useDelivery: vi.fn() }))
vi.mock('../../services/api', () => ({ absoluteFileUrl: (path: string) => `https://api.example.com${path}` }))
vi.mock('../../services/serviceOrders', () => ({ deleteOrderPhoto: vi.fn(), uploadOrderPhoto: vi.fn() }))

const photo = (id: string, fileUrl: string): ApiPhoto => ({
  id,
  phase: 'before',
  file_url: fileUrl,
  original_filename: `${id}.jpg`,
  sort_order: 0,
  created_at: '2026-07-19T00:00:00Z'
})

const page = <PhotoStepPage
  phase='before'
  step={0}
  label='拍施工前照片'
  uploadedTitle='施工前照片已上传'
  missingTitle='请至少添加1张施工前照片'
  nextText='下一步：开始施工'
  nextUrl='/pages/after-photos/index'
/>
const afterPage = <PhotoStepPage
  phase='after'
  step={1}
  label='拍施工后照片'
  uploadedTitle='施工后照片已上传'
  missingTitle='请至少添加1张施工后照片'
  nextText='下一步：说明完成内容'
  nextUrl='/pages/voice/index'
/>

describe('PhotoStepPage synchronization', () => {
  let delivery: {
    serviceOrderId: string
    beforePhotos: string[]
    afterPhotos: string[]
    beforePhotoRecords: ApiPhoto[]
    afterPhotoRecords: ApiPhoto[]
    setBeforePhotos: ReturnType<typeof vi.fn>
    setAfterPhotos: ReturnType<typeof vi.fn>
    setBeforePhotoRecords: ReturnType<typeof vi.fn>
    setAfterPhotoRecords: ReturnType<typeof vi.fn>
  }

  beforeEach(() => {
    vi.resetAllMocks()
    uploaderMock.props = null
    delivery = {
      serviceOrderId: 'order-1',
      beforePhotos: [],
      afterPhotos: [],
      beforePhotoRecords: [],
      afterPhotoRecords: [],
      setBeforePhotos: vi.fn(value => { delivery.beforePhotos = value }),
      setAfterPhotos: vi.fn(value => { delivery.afterPhotos = value }),
      setBeforePhotoRecords: vi.fn(value => { delivery.beforePhotoRecords = value }),
      setAfterPhotoRecords: vi.fn(value => { delivery.afterPhotoRecords = value })
    }
    vi.mocked(useDelivery).mockImplementation(() => delivery as never)
  })

  it('keeps successful uploads and exposes only failed files for retry', async () => {
    const first = photo('photo-1', '/files/photo-1.jpg')
    const second = photo('photo-2', '/files/photo-2.jpg')
    vi.mocked(uploadOrderPhoto)
      .mockResolvedValueOnce(first)
      .mockRejectedValueOnce(new Error('network failed'))

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(page) })
    let uploadError: unknown
    await act(async () => {
      try {
        await uploaderProps().onAdd(['/tmp/one.jpg', '/tmp/two.jpg'])
      } catch (error) {
        uploadError = error
      }
    })

    expect(uploadError).toEqual(new Error('1 张照片上传失败，请点击重试'))
    expect(delivery.beforePhotoRecords).toEqual([first])
    expect(delivery.beforePhotos).toEqual(['https://api.example.com/files/photo-1.jpg'])
    expect(uploaderProps().retryCount).toBe(1)

    vi.mocked(uploadOrderPhoto).mockResolvedValueOnce(second)
    await act(async () => uploaderProps().onRetry())

    expect(uploadOrderPhoto).toHaveBeenLastCalledWith('order-1', 'before', '/tmp/two.jpg')
    expect(delivery.beforePhotoRecords).toEqual([first, second])
    expect(uploaderProps().retryCount).toBe(0)
  })

  it('deletes the server photo before removing it from delivery state', async () => {
    const existing = photo('photo-1', '/files/photo-1.jpg')
    delivery.beforePhotoRecords = [existing]
    delivery.beforePhotos = ['https://api.example.com/files/photo-1.jpg']
    vi.mocked(deleteOrderPhoto).mockResolvedValue(undefined)

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(page) })
    await act(async () => uploaderProps().onRemove(0))

    expect(deleteOrderPhoto).toHaveBeenCalledWith('order-1', 'photo-1')
    expect(delivery.beforePhotoRecords).toEqual([])
    expect(delivery.beforePhotos).toEqual([])
  })

  it('stores after-phase uploads in the after photo state', async () => {
    const uploaded = { ...photo('photo-after', '/files/after.jpg'), phase: 'after' as const }
    vi.mocked(uploadOrderPhoto).mockResolvedValue(uploaded)

    await act(async () => { create(afterPage) })
    await act(async () => uploaderProps().onAdd(['/tmp/after.jpg']))

    expect(uploadOrderPhoto).toHaveBeenCalledWith('order-1', 'after', '/tmp/after.jpg')
    expect(delivery.afterPhotoRecords).toEqual([uploaded])
    expect(delivery.afterPhotos).toEqual(['https://api.example.com/files/after.jpg'])
    expect(delivery.beforePhotos).toEqual([])
  })

  it('keeps the photo when server deletion fails', async () => {
    const existing = photo('photo-1', '/files/photo-1.jpg')
    delivery.beforePhotoRecords = [existing]
    delivery.beforePhotos = ['https://api.example.com/files/photo-1.jpg']
    vi.mocked(deleteOrderPhoto).mockRejectedValue(new Error('删除失败'))

    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(page) })
    let deleteError: unknown
    await act(async () => {
      try {
        await uploaderProps().onRemove(0)
      } catch (error) {
        deleteError = error
      }
    })

    expect(deleteError).toEqual(new Error('删除失败'))
    expect(delivery.beforePhotoRecords).toEqual([existing])
    expect(delivery.beforePhotos).toHaveLength(1)
  })

  it('blocks the next step while failed uploads are waiting for retry', async () => {
    vi.mocked(uploadOrderPhoto).mockRejectedValue(new Error('network failed'))
    let renderer!: ReturnType<typeof create>
    await act(async () => { renderer = create(page) })
    await act(async () => {
      try {
        await uploaderProps().onAdd(['/tmp/failed.jpg'])
      } catch {
        // The uploader displays the returned error to the user.
      }
    })
    await act(async () => renderer.root.findByType('button').props.onClick())

    expect(Taro.navigateTo).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith({ title: '请先重试上传失败的照片', icon: 'none' })
  })
})
