import PhotoStepPage from '../../components/PhotoStepPage'

export default function BeforePhotos() {
  return <PhotoStepPage
    phase='before'
    step={0}
    label='拍施工前照片'
    uploadedTitle='施工前照片已上传'
    missingTitle='请至少添加1张施工前照片'
    nextText='下一步：开始施工'
    nextUrl='/pages/after-photos/index'
  />
}
