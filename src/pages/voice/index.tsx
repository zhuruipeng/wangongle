import Taro from '@tarojs/taro'
import { Button, Text, Textarea, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import StepProgress from '../../components/StepProgress'
import { useDelivery } from '../../context/DeliveryContext'
import { recognitionExample } from '../../mock/service'
import { generateOrderReport, patchServiceOrder, transcribeOrderAudio, uploadOrderAudio } from '../../services/serviceOrders'
import './index.scss'

declare const __GANWANLE_DEV__: boolean

type RecorderPhase = 'idle' | 'recording' | 'stopping' | 'uploading' | 'transcribing' | 'ready' | 'error'
type StopResult = { tempFilePath: string; duration?: number }
type RecorderError = { errMsg?: string }
type RecorderHandlers = { onStart: () => void; onStop: (result: StopResult) => void; onError: (error: RecorderError) => void }

const MAX_SECONDS = 45
const MIN_DURATION_MS = 800

// RecorderManager is globally unique. Register its listeners once and route events
// to only the currently mounted voice page, because this Taro version has no offStop/offError.
const recorderManager = Taro.getRecorderManager()
let activeHandlers: RecorderHandlers | null = null
recorderManager.onStart(() => activeHandlers?.onStart())
recorderManager.onStop(result => activeHandlers?.onStop(result))
recorderManager.onError(error => activeHandlers?.onError(error))

export default function Voice() {
  const { serviceOrderId, voicePath, setVoicePath, description, setDescription, setReport, setGeneratedReport, setRemoteOrder } = useDelivery()
  const [phase, setPhaseState] = useState<RecorderPhase>('idle')
  const [remaining, setRemaining] = useState(MAX_SECONDS)
  const [speechError, setSpeechError] = useState('')
  const [aiError, setAiError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [newAudioUploaded, setNewAudioUploaded] = useState(false)

  const mountedRef = useRef(false)
  const phaseRef = useRef<RecorderPhase>('idle')
  const recordingRef = useRef(false)
  const stopRequestedRef = useRef(false)
  const processingRef = useRef(false)
  const currentSessionIdRef = useRef(0)
  const startedAtRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setInterval>>()

  const setPhase = (next: RecorderPhase) => { phaseRef.current = next; if (mountedRef.current) setPhaseState(next) }
  const stopTimer = () => { if (timerRef.current) clearInterval(timerRef.current); timerRef.current = undefined }
  const isProcessing = phase === 'stopping' || phase === 'uploading' || phase === 'transcribing' || submitting

  const runTranscription = async (sessionId: number) => {
    if (!serviceOrderId || processingRef.current) return
    processingRef.current = true
    setPhase('transcribing'); setSpeechError('')
    try {
      const result = await transcribeOrderAudio(serviceOrderId)
      if (!mountedRef.current || sessionId !== currentSessionIdRef.current) return
      if (result.status === 'failed' || !result.transcript) throw new Error(result.error || '语音识别失败')
      setDescription(result.transcript)
      setPhase('ready')
      Taro.showToast({ title: '识别成功', icon: 'success' })
    } catch (error) {
      if (!mountedRef.current || sessionId !== currentSessionIdRef.current) return
      const message = error instanceof Error ? error.message : '语音识别失败'
      setSpeechError(message)
      setPhase('error')
      Taro.showToast({ title: message === '语音服务尚未配置' ? message : '语音识别失败，可直接输入文字', icon: 'none', duration: 3000 })
    } finally {
      if (sessionId === currentSessionIdRef.current) processingRef.current = false
    }
  }

  useEffect(() => {
    mountedRef.current = true
    const handlers: RecorderHandlers = {
      onStart: () => {
        if (!mountedRef.current) return
        recordingRef.current = true
        setPhase('recording')
      },
      onStop: result => {
        const sessionId = currentSessionIdRef.current
        recordingRef.current = false
        stopRequestedRef.current = false
        stopTimer()
        setRemaining(MAX_SECONDS)
        const duration = result.duration ?? Math.max(0, Date.now() - startedAtRef.current)
        if (!result.tempFilePath) {
          setSpeechError('未获取到录音文件，请重新录制')
          setPhase('error')
          return
        }
        if (duration < MIN_DURATION_MS) {
          setSpeechError('录音时间太短，请重新录制')
          setPhase('error')
          return
        }
        if (!serviceOrderId) {
          setSpeechError('缺少服务单，请从工作台重新开始')
          setPhase('error')
          return
        }
        processingRef.current = true
        setPhase('uploading')
        uploadOrderAudio(serviceOrderId, result.tempFilePath)
          .then(() => {
            if (!mountedRef.current || sessionId !== currentSessionIdRef.current) return
            setVoicePath(result.tempFilePath)
            setNewAudioUploaded(true)
            processingRef.current = false
            return runTranscription(sessionId)
          })
          .catch(error => {
            if (!mountedRef.current || sessionId !== currentSessionIdRef.current) return
            setSpeechError(error instanceof Error ? error.message : '录音上传失败')
            setPhase('error')
          })
          .finally(() => {
            if (sessionId === currentSessionIdRef.current && phaseRef.current !== 'transcribing') processingRef.current = false
          })
      },
      onError: error => {
        if (!mountedRef.current) return
        stopTimer()
        recordingRef.current = false
        stopRequestedRef.current = false
        processingRef.current = false
        const errMsg = error.errMsg || 'unknown recorder error'
        if (__GANWANLE_DEV__) console.error('[voice recorder]', { errMsg, phase: phaseRef.current, sessionId: currentSessionIdRef.current })
        const permissionDenied = /auth|authorize|permission|deny/i.test(errMsg)
        setSpeechError(permissionDenied ? '请在微信设置中开启麦克风权限' : '录音未能开始，请重新录制')
        setPhase('error')
        Taro.showToast({ title: permissionDenied ? '请开启麦克风权限' : '录音失败，可以直接输入文字', icon: 'none' })
      }
    }
    activeHandlers = handlers
    return () => {
      mountedRef.current = false
      stopTimer()
      if (recordingRef.current && !stopRequestedRef.current) {
        stopRequestedRef.current = true
        recorderManager.stop()
      }
      recordingRef.current = false
      processingRef.current = false
      if (activeHandlers === handlers) activeHandlers = null
    }
  }, [serviceOrderId, setDescription, setVoicePath])

  const startRecording = () => {
    const current = phaseRef.current
    if (current === 'stopping' || current === 'uploading' || current === 'transcribing' || processingRef.current) {
      Taro.showToast({ title: '正在处理上一段录音，请稍候', icon: 'none' })
      return
    }
    if (!['idle', 'ready', 'error'].includes(current) || recordingRef.current) return
    currentSessionIdRef.current += 1
    stopRequestedRef.current = false
    processingRef.current = false
    recordingRef.current = true
    startedAtRef.current = Date.now()
    setSpeechError('')
    setNewAudioUploaded(false)
    setRemaining(MAX_SECONDS)
    setPhase('recording')
    recorderManager.start({ duration: MAX_SECONDS * 1000, sampleRate: 16000, numberOfChannels: 1, encodeBitRate: 48000, format: 'mp3' })
    timerRef.current = setInterval(() => setRemaining(value => Math.max(0, value - 1)), 1000)
  }

  const stopRecording = () => {
    if (!recordingRef.current || stopRequestedRef.current) return
    stopRequestedRef.current = true
    recordingRef.current = false
    setPhase('stopping')
    recorderManager.stop()
  }

  const retryTranscription = () => {
    if (!newAudioUploaded || processingRef.current) return
    runTranscription(currentSessionIdRef.current)
  }

  const next = async () => {
    const transcript = description.trim()
    if (!transcript || isProcessing || submitting) return
    if (!serviceOrderId) return Taro.showToast({ title: '缺少服务单，请从工作台重新开始', icon: 'none' })
    setSubmitting(true)
    setAiError('')
    try {
      const order = await patchServiceOrder(serviceOrderId, { transcript })
      setRemoteOrder(order)
      let force = false
      if (order.report) {
        const confirmation = await Taro.showModal({ title: '重新生成报告', content: '该服务单已有报告，重新生成会覆盖尚未保存的AI整理内容。是否继续？', confirmText: '继续生成' })
        if (!confirmation.confirm) return
        force = true
      }
      const generated = await generateOrderReport(serviceOrderId, force)
      const materialAmounts = generated.report.materials.map(item => item.amount_cents).filter((value): value is number => value !== null)
      const laborAmount = generated.report.labor_items[0]?.amount_cents
      setGeneratedReport(generated.report)
      setReport({
        completed: generated.report.completed_items.map(item => item.content),
        materials: generated.report.materials.map(item => ({
          name: item.name,
          quantity: item.quantity === null ? item.unit : `${item.quantity}${item.unit}`,
          unitPrice: item.unit_price_cents === null ? '' : String(item.unit_price_cents / 100),
          price: item.amount_cents === null ? '' : String(item.amount_cents / 100)
        })),
        serviceFee: laborAmount === null || laborAmount === undefined ? '' : String(laborAmount / 100),
        materialFee: materialAmounts.length ? String(materialAmounts.reduce((sum, value) => sum + value, 0) / 100) : '',
        paid: String(generated.paid_amount_cents / 100),
        risks: generated.report.risks.map(item => item.content),
        afterSales: generated.report.after_sales.map(item => item.content).join('；')
      })
      await Taro.navigateTo({ url: '/pages/report/index' })
    } catch (error) {
      setAiError('AI整理失败，可直接手工填写')
      Taro.showToast({ title: error instanceof Error ? error.message : 'AI整理失败，可直接手工填写', icon: 'none', duration: 3000 })
    }
    finally { setSubmitting(false) }
  }

  const openManualReport = async () => {
    setGeneratedReport(null)
    setReport({ completed: [''], materials: [], serviceFee: '', materialFee: '', paid: '0', risks: [], afterSales: '' })
    await Taro.navigateTo({ url: '/pages/report/index' })
  }

  const statusText: Record<RecorderPhase, string> = {
    idle: '松开后自动上传并识别', recording: `正在录音，剩余 ${remaining} 秒`, stopping: '正在结束录音...',
    uploading: '正在上传录音', transcribing: '正在识别，请稍候', ready: '✓ 识别成功，可继续修改文字',
    error: '录音或识别未完成，你可以重新录音或直接输入。'
  }
  const buttonText = phase === 'recording' ? '松开结束' : isProcessing ? '处理中...' : phase === 'idle' ? '按住说话' : '重新录音'

  return <View className='page voice-page'><StepProgress current={2} />
    <View className='example card'><Text className='section-title'>可以这样说</Text><Text>“{recognitionExample}”</Text></View>
    <View className={`record ${phase === 'recording' ? 'recording' : ''} ${isProcessing ? 'disabled' : ''}`} onTouchStart={startRecording} onTouchEnd={stopRecording} onTouchCancel={stopRecording}>
      <Text className='mic'>🎙️</Text><Text>{buttonText}</Text>{phase === 'recording' && <Text className='countdown'>剩余 {remaining} 秒</Text>}
    </View>
    <Text className={`record-status state-${phase}`}>{statusText[phase]}</Text>
    {speechError && <Text className='speech-error'>{speechError}</Text>}
    {phase === 'error' && newAudioUploaded && <View className='speech-actions'><Button className='small-action' disabled={processingRef.current} onClick={retryTranscription}>重新识别</Button></View>}
    <View className='manual'><Text className='section-title'>手动输入或修改识别文字</Text>
      <Textarea className='text-area' value={description} maxlength={500} placeholder='请输入本次完成内容、所用材料和异常情况' onInput={e => setDescription(e.detail.value)} />
    </View>
    {aiError && <View className='speech-error'><Text>{aiError}</Text><Button className='small-action' onClick={openManualReport}>直接手工填写报告</Button></View>}
    <View className='fixed-actions'><Button className='primary-btn' loading={submitting} disabled={!description.trim() || isProcessing || phase === 'recording' || submitting} onClick={next}>{submitting ? '正在整理服务报告' : 'AI生成报告'}</Button></View>
  </View>
}
