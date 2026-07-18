import Taro, { getCurrentInstance } from '@tarojs/taro'
import { Button, Checkbox, CheckboxGroup, Image, Input, Text, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import SignaturePad, { type SignaturePadHandle } from '../../components/SignaturePad'
import { absoluteFileUrl } from '../../services/api'
import {
  confirmPublicAcceptance,
  getPublicAcceptance,
  PublicAcceptanceError,
  type PublicAcceptanceData
} from '../../services/publicAcceptance'
import './index.scss'

type PageState = 'loading' | 'waiting' | 'accepted' | 'expired' | 'revoked' | 'invalid' | 'network'
const TOKEN_STORAGE_KEY = 'ganwanleAcceptanceToken'
const ACCEPTED_SNAPSHOT_KEY = 'ganwanleAcceptedSnapshot'
let tokenInMemory = ''

export default function CustomerAcceptance() {
  const signatureRef = useRef<SignaturePadHandle>(null)
  const [pageState, setPageState] = useState<PageState>('loading')
  const [data, setData] = useState<PublicAcceptanceData | null>(null)
  const [token, setToken] = useState('')
  const [acceptedStatement, setAcceptedStatement] = useState(false)
  const [signed, setSigned] = useState(false)
  const [signerName, setSignerName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    configureNoIndex()
    void loadAcceptance()
  }, [])

  const loadAcceptance = async () => {
    setPageState('loading')
    setErrorMessage('')
    const activeToken = readAndHideToken()
    if (!activeToken) {
      const cached = readAcceptedSnapshot()
      if (cached) {
        setData(cached)
        setSignerName(cached.customer_name)
        setAcceptedStatement(true)
        setPageState('accepted')
        return
      }
      setPageState('invalid')
      setErrorMessage('验收链接无效')
      return
    }
    setToken(activeToken)
    try {
      const response = await getPublicAcceptance(activeToken)
      setData(response)
      setSignerName(response.customer_name)
      if (response.status === 'accepted') {
        setAcceptedStatement(true)
        cacheAcceptedSnapshot(response)
        setPageState('accepted')
      } else {
        setPageState('waiting')
      }
    } catch (error) {
      applyLoadError(error)
    }
  }

  const applyLoadError = (error: unknown) => {
    const message = error instanceof Error ? error.message : '网络连接失败'
    setErrorMessage(message)
    if (error instanceof PublicAcceptanceError) {
      if (message.includes('过期')) return setPageState('expired')
      if (message.includes('撤销')) return setPageState('revoked')
      if (error.status === 401) return setPageState('invalid')
    }
    setPageState('network')
  }

  const confirm = async () => {
    if (submitting || pageState !== 'waiting') return
    if (!acceptedStatement) return Taro.showToast({ title: '请先勾选客户验收声明', icon: 'none' })
    if (!signerName.trim()) return Taro.showToast({ title: '请填写客户姓名', icon: 'none' })
    if (!signed) return Taro.showToast({ title: '请先完成手写签名', icon: 'none' })
    if (!token || !signatureRef.current) return Taro.showToast({ title: '验收链接无效，请重新打开', icon: 'none' })
    setSubmitting(true)
    try {
      const signature = await signatureRef.current.exportPng()
      const response = await confirmPublicAcceptance(token, signerName.trim(), signature)
      finishAcceptance(response)
    } catch (error) {
      if (error instanceof PublicAcceptanceError && error.status === 409 && error.message.includes('已经验收')) {
        try {
          finishAcceptance(await getPublicAcceptance(token))
          return
        } catch {
          // Fall through to the original readable duplicate-submission message.
        }
      }
      if (error instanceof PublicAcceptanceError && (error.status === 401 || error.status === 410)) {
        setData(null)
        applyLoadError(error)
        return
      }
      Taro.showToast({ title: error instanceof Error ? error.message : '确认验收失败', icon: 'none', duration: 3000 })
    } finally {
      setSubmitting(false)
    }
  }

  const finishAcceptance = (response: PublicAcceptanceData) => {
    setData(response)
    setPageState('accepted')
    setAcceptedStatement(true)
    tokenInMemory = ''
    setToken('')
    if (Taro.getEnv() === Taro.ENV_TYPE.WEB) {
      sessionStorage.removeItem(TOKEN_STORAGE_KEY)
      cacheAcceptedSnapshot(response)
    }
    Taro.showModal({ title: '验收成功', content: '感谢您的确认，本次服务已完成验收。', showCancel: false })
  }

  if (!data) {
    return <View className='acceptance-page state-page'>
      <View className='acceptance-header'><Text className='acceptance-brand'>干完了</Text><Text className='company'>客户验收</Text></View>
      <View className='acceptance-card state-card'>
        <Text className='acceptance-section-title'>{stateTitle(pageState)}</Text>
        <Text className='state-description'>{pageState === 'loading' ? '正在安全读取服务报告，请稍候…' : errorMessage}</Text>
        {pageState === 'network' && <Button className='retry-button' onClick={loadAcceptance}>重新加载</Button>}
      </View>
      <Text className='noindex-note'>本验收页已设置为禁止搜索引擎收录。</Text>
    </View>
  }

  const finished = pageState === 'accepted'
  const beforePhotos = data.before_photos.map(item => absoluteFileUrl(item.file_url))
  const afterPhotos = data.after_photos.map(item => absoluteFileUrl(item.file_url))

  return <View className='acceptance-page'>
    <View className={`acceptance-header ${finished ? 'finished' : ''}`}>
      <Text className='acceptance-brand'>干完了</Text><Text className='company'>{data.company_name}</Text>
      <Text className='acceptance-status'>{finished ? '✓ 服务已验收' : '状态：等待客户验收'}</Text>
      <Text className='order-number'>服务单号：{data.order_no}</Text>
      {finished && data.accepted_at && <Text className='finish-time'>确认时间：{formatTime(data.accepted_at)}</Text>}
    </View>

    <Section title='客户和服务信息'>
      <Info label='客户' value={data.customer_name} /><Info label='服务地址' value={data.service_address} />
      <Info label='服务项目' value={data.service_type} /><Info label='服务师傅' value={data.technician_name} />
      <Info label='完工时间' value={formatTime(data.completed_at)} />
    </Section>

    <Section title='施工前后照片'><PhotoArea title='施工前' photos={beforePhotos} /><PhotoArea title='施工后' photos={afterPhotos} /></Section>
    <Section title='完成内容'>{data.completed_items.map((item, index) => <View className='check-line' key={index}><Text className='check-icon'>✓</Text><Text>{item}</Text></View>)}</Section>
    <Section title='使用材料'>
      {data.materials.length ? data.materials.map((item, index) => <View className='material-line' key={index}><View><Text className='material-title'>{item.name}</Text><Text className='material-quantity'>{item.quantity}</Text></View><Text className='material-price'>{moneyText(item.amount_cents)}</Text></View>) : <Text className='empty-line'>本次服务未记录材料。</Text>}
    </Section>
    <Section title='工时及费用'>
      {data.fee_items.map((item, index) => <PriceLine key={index} label={item.name} value={item.amount_cents} />)}
      <View className='price-highlight'><Text>合计</Text><Text>{moneyText(data.total_amount_cents)}</Text></View>
      <PriceLine label='已收' value={data.paid_amount_cents} />
      <View className='price-highlight due'><Text>待收</Text><Text>{moneyText(data.due_amount_cents)}</Text></View>
    </Section>

    <View className='acceptance-card risk-card'><Text className='acceptance-section-title'>风险和异常</Text>{data.risks.length ? data.risks.map((item, index) => <Text className='risk-line' key={index}>• {item}</Text>) : <Text className='risk-line'>本次服务未记录异常。</Text>}</View>
    <Section title='售后提醒'><Text className='after-sales'>{data.after_sales_reminder || '本次服务未记录售后提醒。'}</Text></Section>

    {!finished ? <Section title='客户确认'>
      <CheckboxGroup onChange={event => setAcceptedStatement(event.detail.value.includes('accepted'))}><View className='confirm-check'><Checkbox value='accepted' checked={acceptedStatement} color='#173b65' /><Text>{data.acceptance_statement}</Text></View></CheckboxGroup>
      <Text className='signature-title'>客户姓名</Text><Input className='signer-input' value={signerName} maxlength={100} placeholder='请输入验收人姓名' onInput={event => setSignerName(event.detail.value)} />
      <Text className='signature-title'>客户手写签名</Text><SignaturePad ref={signatureRef} signed={signed} disabled={submitting} onSignedChange={setSigned} />
    </Section> : <View className='acceptance-card locked-card'><Text>✓ 客户签名已保存</Text><Text>该服务单已验收，内容已锁定。</Text></View>}

    {finished && <View className='success-message'>✓ 感谢您的确认，本次服务已完成验收。</View>}
    <Text className='noindex-note'>本验收页已设置为禁止搜索引擎收录。</Text>
    <View className='acceptance-fixed'><Button className='primary-btn' loading={submitting} disabled={finished || submitting} onClick={confirm}>{finished ? '验收已完成' : submitting ? '正在确认验收' : '确认验收'}</Button></View>
  </View>
}

function Section({ title, children }: { title: string; children: React.ReactNode }) { return <View className='acceptance-card'><Text className='acceptance-section-title'>{title}</Text>{children}</View> }
function Info({ label, value }: { label: string; value: string }) { return <View className='info-line'><Text>{label}</Text><Text>{value}</Text></View> }
function PriceLine({ label, value }: { label: string; value: number | null }) { return <View className='price-line'><Text>{label}</Text><Text>{moneyText(value)}</Text></View> }
function PhotoArea({ title, photos }: { title: string; photos: string[] }) { return <View className='photo-area'><Text className='photo-area-title'>{title}</Text>{photos.length ? <View className='acceptance-photos'>{photos.map(photo => <Image key={photo} src={photo} mode='aspectFill' onClick={() => Taro.previewImage({ current: photo, urls: photos })} />)}</View> : <View className='photo-empty'>暂无{title}照片</View>}</View> }
function moneyText(value: number | null) { return value === null ? '待确认' : `¥${(value / 100).toFixed(2)}` }
function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false }) }
function stateTitle(state: PageState) { return ({ loading: '正在加载', waiting: '等待验收', accepted: '服务已验收', expired: '链接已过期', revoked: '链接已撤销', invalid: '链接无效', network: '网络错误' } as Record<PageState, string>)[state] }

function configureNoIndex() {
  if (Taro.getEnv() !== Taro.ENV_TYPE.WEB) return
  let meta = document.querySelector('meta[name="robots"]') as HTMLMetaElement | null
  if (!meta) { meta = document.createElement('meta'); meta.name = 'robots'; document.head.appendChild(meta) }
  meta.content = 'noindex,nofollow,noarchive'
}

function readAndHideToken() {
  const routerToken = getCurrentInstance().router?.params?.token || ''
  if (Taro.getEnv() !== Taro.ENV_TYPE.WEB) { tokenInMemory = routerToken || tokenInMemory; return tokenInMemory }
  const url = new URL(window.location.href)
  const urlToken = routerToken || url.searchParams.get('token') || ''
  if (urlToken) {
    sessionStorage.removeItem(ACCEPTED_SNAPSHOT_KEY)
    sessionStorage.setItem(TOKEN_STORAGE_KEY, urlToken)
    url.searchParams.delete('token')
    window.history.replaceState({}, document.title, `${url.pathname}${url.search}${url.hash}`)
  }
  tokenInMemory = urlToken || sessionStorage.getItem(TOKEN_STORAGE_KEY) || ''
  return tokenInMemory
}

function cacheAcceptedSnapshot(value: PublicAcceptanceData) { if (Taro.getEnv() === Taro.ENV_TYPE.WEB) sessionStorage.setItem(ACCEPTED_SNAPSHOT_KEY, JSON.stringify(value)) }
function readAcceptedSnapshot(): PublicAcceptanceData | null {
  if (Taro.getEnv() !== Taro.ENV_TYPE.WEB) return null
  try { const value = sessionStorage.getItem(ACCEPTED_SNAPSHOT_KEY); return value ? JSON.parse(value) as PublicAcceptanceData : null } catch { return null }
}
