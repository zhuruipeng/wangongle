import PhotoStepPage from '../../components/PhotoStepPage'

export default function AfterPhotos() {
  return <PhotoStepPage
    phase='after'
    step={1}
    label='拍施工后照片'
    uploadedTitle='施工后照片已上传'
    missingTitle='请至少添加1张施工后照片'
    nextText='下一步：说明完成内容'
    nextUrl='/pages/voice/index'
  />
}
