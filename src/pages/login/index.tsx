import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useEffect } from 'react'
import { useAuth } from '../../context/AuthContext'
import './index.scss'

export default function LoginPage() {
  const { status, user, error, retry } = useAuth()

  useEffect(() => {
    if (status === 'authenticated' && user?.profile_complete) {
      void Taro.reLaunch({ url: '/pages/workbench/index' })
    }
  }, [status, user])

  const failed = status === 'anonymous'
  return <View className='page login-page'>
    <View className={`work-order-stamp ${failed ? 'is-failed' : ''}`}>
      <Text className='stamp-kicker'>现场工单</Text>
      <Text className='stamp-state'>{failed ? '待重试' : '连接中'}</Text>
    </View>
    <View className='login-copy'>
      <Text className='page-title'>{failed ? '身份确认未完成' : '正在确认微信身份'}</Text>
      <Text className='login-description'>授权完成后即可进入工作台，不需要输入账号或密码。</Text>
    </View>
    {failed
      ? <View className='login-error card'>
          <Text className='error-label'>本次连接失败</Text>
          <Text className='error-message'>{error || '微信登录失败，请检查网络后重试'}</Text>
          <Button className='primary-btn retry-btn' onClick={retry}>重新连接</Button>
        </View>
      : <View className='login-progress card'>
          <View className='status-dot' />
          <Text>正在安全连接微信…</Text>
        </View>}
    <Text className='login-footnote'>仅用于识别当前服务师傅</Text>
  </View>
}
