import Taro from '@tarojs/taro'
import { createContext, useContext, useEffect, useMemo, useState, type PropsWithChildren } from 'react'
import { useAuth } from './AuthContext'
import { initialReport } from '../mock/service'
import type { ApiAiServiceReportDraft, ApiGeneratedReport, ApiServiceOrder } from '../services/serviceOrders'

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
type DeliveryState = {
  serviceOrderId: string; remoteOrder: ApiServiceOrder | null
  aiReport: ApiAiServiceReportDraft | null
  generatedReport: ApiGeneratedReport | null; reportConfirmed: boolean
  beforePhotos: string[]; afterPhotos: string[]; voicePath: string; description: string; report: Report
  setServiceOrderId: (v: string) => void; setRemoteOrder: (v: ApiServiceOrder | null) => void
  setAiReport: (v: ApiAiServiceReportDraft | null) => void
  setGeneratedReport: (v: ApiGeneratedReport | null) => void; setReportConfirmed: (v: boolean) => void
  setBeforePhotos: (v: string[]) => void; setAfterPhotos: (v: string[]) => void
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
  const [voicePath, setVoicePath] = useState('')
  const [description, setDescription] = useState('')
  const [report, setReport] = useState<Report>(initialReport)
  const clearDeliveryState = () => {
    setServiceOrderIdState('')
    setRemoteOrder(null)
    setAiReport(null)
    setGeneratedReportState(null)
    setReportConfirmed(false)
    setBeforePhotos([])
    setAfterPhotos([])
    setVoicePath('')
    setDescription('')
    setReport(initialReport)
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
  const setGeneratedReport = (value: ApiGeneratedReport | null) => { setGeneratedReportState(value); setReportConfirmed(false) }
  const value = useMemo(() => ({ serviceOrderId, remoteOrder, aiReport, generatedReport, reportConfirmed, beforePhotos, afterPhotos, voicePath, description, report,
    setServiceOrderId, setRemoteOrder, setAiReport, setGeneratedReport, setReportConfirmed,
    setBeforePhotos, setAfterPhotos, setVoicePath, setDescription, setReport
  }), [serviceOrderId, remoteOrder, aiReport, generatedReport, reportConfirmed, beforePhotos, afterPhotos, voicePath, description, report])
  return <DeliveryContext.Provider value={value}>{children}</DeliveryContext.Provider>
}

export function useDelivery() {
  const value = useContext(DeliveryContext)
  if (!value) throw new Error('useDelivery must be used inside DeliveryProvider')
  return value
}
