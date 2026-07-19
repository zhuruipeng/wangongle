import Taro from '@tarojs/taro'
import { createContext, useContext, useEffect, useMemo, useState, type PropsWithChildren } from 'react'
import { useAuth } from './AuthContext'
import { absoluteFileUrl } from '../services/api'
import type { ApiAiServiceReportDraft, ApiGeneratedReport, ApiPhoto, ApiServiceOrder } from '../services/serviceOrders'

export type Material = { name: string; quantity: string; unitPrice?: string; price: string }
export type Report = {
  completed: string[]
  materials: Material[]
  serviceFee: string
  materialFee: string
  paid: string
  risks: string[]
  afterSales: string
}

const createEmptyReport = (): Report => ({
  completed: [],
  materials: [],
  serviceFee: '0',
  materialFee: '0',
  paid: '0',
  risks: [],
  afterSales: ''
})

function reportFromOrder(order: ApiServiceOrder): Report {
  if (!order.report) return createEmptyReport()
  return {
    completed: order.report.completed_items,
    materials: order.report.materials.map(item => ({
      name: item.name,
      quantity: item.quantity,
      price: item.amount_cents === null ? '' : String(item.amount_cents / 100)
    })),
    serviceFee: String((order.report.fee_items.find(item => item.name === '安装服务费')?.amount_cents || 0) / 100),
    materialFee: String((order.report.fee_items.find(item => item.name === '材料费')?.amount_cents || 0) / 100),
    paid: String(order.report.paid_amount_cents / 100),
    risks: order.report.risks,
    afterSales: order.report.after_sales_reminder
  }
}

type DeliveryState = {
  serviceOrderId: string; remoteOrder: ApiServiceOrder | null
  aiReport: ApiAiServiceReportDraft | null
  generatedReport: ApiGeneratedReport | null; reportConfirmed: boolean
  beforePhotos: string[]; afterPhotos: string[]; beforePhotoRecords: ApiPhoto[]; afterPhotoRecords: ApiPhoto[]
  voicePath: string; description: string; report: Report
  setServiceOrderId: (v: string) => void; setRemoteOrder: (v: ApiServiceOrder | null) => void
  selectServiceOrder: (order: ApiServiceOrder) => void
  setAiReport: (v: ApiAiServiceReportDraft | null) => void
  setGeneratedReport: (v: ApiGeneratedReport | null) => void; setReportConfirmed: (v: boolean) => void
  setBeforePhotos: (v: string[]) => void; setAfterPhotos: (v: string[]) => void
  setBeforePhotoRecords: (v: ApiPhoto[]) => void; setAfterPhotoRecords: (v: ApiPhoto[]) => void
  setVoicePath: (v: string) => void; setDescription: (v: string) => void; setReport: (v: Report) => void
}

const DeliveryContext = createContext<DeliveryState | null>(null)

export function DeliveryProvider({ children }: PropsWithChildren) {
  const { status: authStatus, user } = useAuth()
  const storageKey = authStatus === 'authenticated' && user?.profile_complete ? `ganwanleServiceOrderId:${user.id}` : ''
  const [activeStorageKey, setActiveStorageKey] = useState('')
  const [serviceOrderId, setServiceOrderIdState] = useState('')
  const [remoteOrder, setRemoteOrder] = useState<ApiServiceOrder | null>(null)
  const [aiReport, setAiReport] = useState<ApiAiServiceReportDraft | null>(null)
  const [generatedReport, setGeneratedReportState] = useState<ApiGeneratedReport | null>(null)
  const [reportConfirmed, setReportConfirmed] = useState(false)
  const [beforePhotos, setBeforePhotos] = useState<string[]>([])
  const [afterPhotos, setAfterPhotos] = useState<string[]>([])
  const [beforePhotoRecords, setBeforePhotoRecords] = useState<ApiPhoto[]>([])
  const [afterPhotoRecords, setAfterPhotoRecords] = useState<ApiPhoto[]>([])
  const [voicePath, setVoicePath] = useState('')
  const [description, setDescription] = useState('')
  const [report, setReport] = useState<Report>(createEmptyReport)
  const clearDeliveryState = () => {
    setServiceOrderIdState('')
    setRemoteOrder(null)
    setAiReport(null)
    setGeneratedReportState(null)
    setReportConfirmed(false)
    setBeforePhotos([])
    setAfterPhotos([])
    setBeforePhotoRecords([])
    setAfterPhotoRecords([])
    setVoicePath('')
    setDescription('')
    setReport(createEmptyReport())
  }

  useEffect(() => {
    if (!storageKey) {
      setActiveStorageKey('')
      clearDeliveryState()
      if (authStatus === 'anonymous') Taro.removeStorageSync('ganwanleServiceOrderId')
      return
    }
    if (storageKey === activeStorageKey) return
    clearDeliveryState()
    setActiveStorageKey(storageKey)
  }, [activeStorageKey, authStatus, storageKey])

  useEffect(() => {
    if (!activeStorageKey || activeStorageKey !== storageKey) return
    setServiceOrderIdState(Taro.getStorageSync<string>(activeStorageKey) || '')
  }, [activeStorageKey, storageKey])

  const setServiceOrderId = (value: string) => {
    setServiceOrderIdState(value)
    if (!storageKey) return
    value ? Taro.setStorageSync(storageKey, value) : Taro.removeStorageSync(storageKey)
  }
  const selectServiceOrder = (order: ApiServiceOrder) => {
    setServiceOrderId(order.id)
    setRemoteOrder(order)
    setAiReport(order.ai_report)
    setGeneratedReportState(order.generated_report)
    setReportConfirmed(Boolean(order.report || order.ai_report))
    setBeforePhotos(order.before_photos.map(photo => absoluteFileUrl(photo.file_url)))
    setAfterPhotos(order.after_photos.map(photo => absoluteFileUrl(photo.file_url)))
    setBeforePhotoRecords(order.before_photos)
    setAfterPhotoRecords(order.after_photos)
    setVoicePath(order.audio_url ? absoluteFileUrl(order.audio_url) : '')
    setDescription(order.transcript || '')
    setReport(reportFromOrder(order))
  }
  const setGeneratedReport = (value: ApiGeneratedReport | null) => { setGeneratedReportState(value); setReportConfirmed(false) }
  const value = useMemo(() => ({ serviceOrderId, remoteOrder, aiReport, generatedReport, reportConfirmed, beforePhotos, afterPhotos, beforePhotoRecords, afterPhotoRecords, voicePath, description, report,
    setServiceOrderId, setRemoteOrder, selectServiceOrder, setAiReport, setGeneratedReport, setReportConfirmed,
    setBeforePhotos, setAfterPhotos, setBeforePhotoRecords, setAfterPhotoRecords, setVoicePath, setDescription, setReport
  }), [serviceOrderId, remoteOrder, aiReport, generatedReport, reportConfirmed, beforePhotos, afterPhotos, beforePhotoRecords, afterPhotoRecords, voicePath, description, report])
  return <DeliveryContext.Provider value={value}>{children}</DeliveryContext.Provider>
}

export function useDelivery() {
  const value = useContext(DeliveryContext)
  if (!value) throw new Error('useDelivery must be used inside DeliveryProvider')
  return value
}
