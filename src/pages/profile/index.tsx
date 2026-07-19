import Taro from '@tarojs/taro'
import { Button, Input, Text, View } from '@tarojs/components'
import { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { apiRequest } from '../../services/api'
import type { AuthUser } from '../../services/session'
import './index.scss'

export default function ProfilePage() {
  const { user, setUser } = useAuth()
  const [name, setName] = useState(user?.technician_name || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const saveProfile = async () => {
    if (saving) return
    const technicianName = name.trim()
    if (!technicianName) {
      setError('请输入现场服务使用的姓名')
      return
    }
    if (technicianName.length > 100) {
      setError('姓名不能超过 100 个字符')
      return
    }
    setSaving(true)
    setError('')
    try {
      const completedUser = await apiRequest<AuthUser>('/api/v1/auth/me/profile', {
        method: 'PATCH',
        data: { technician_name: technicianName }
      })
      setUser(completedUser)
      void Taro.reLaunch({ url: '/pages/workbench/index' })
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '姓名保存失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  return <View className='page profile-page'>
    <View className='profile-heading'>
      <View className='profile-stamp'><Text>师傅资料</Text></View>
      <Text className='page-title'>开工前，留下您的姓名</Text>
      <Text className='profile-description'>姓名会显示在服务单和客户验收页，方便客户确认现场服务人员。</Text>
    </View>
    <View className='profile-form card'>
      <View className='field'>
        <Text className='field-label'>师傅姓名</Text>
        <Input
          className='text-input'
          value={name}
          maxlength={100}
          placeholder='例如：王师傅'
          focus
          onInput={event => { setName(event.detail.value); setError('') }}
        />
        <Text className='field-helper'>请填写客户认识您的称呼，1–100 个字符。</Text>
        {!!error && <Text className='field-error'>{error}</Text>}
      </View>
      <Button className='primary-btn save-profile-btn' loading={saving} disabled={saving} onClick={saveProfile}>
        {saving ? '正在保存…' : '保存并进入工作台'}
      </Button>
    </View>
  </View>
}
