import Taro from '@tarojs/taro'
import { createContext, useContext, useMemo, useState, type PropsWithChildren } from 'react'
import { initialReport } from '../mock/service'
import type { ApiGeneratedReport, ApiServiceOrder } from '../services/serviceOrders'

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
  generatedReport: ApiGeneratedReport | null; reportConfirmed: boolean
  beforePhotos: string[]; afterPhotos: string[]; voicePath: string; description: string; report: Report
  setServiceOrderId: (v: string) => void; setRemoteOrder: (v: ApiServiceOrder | null) => void
  setGeneratedReport: (v: ApiGeneratedReport | null) => void; setReportConfirmed: (v: boolean) => void
  setBeforePhotos: (v: string[]) => void; setAfterPhotos: (v: string[]) => void
  setVoicePath: (v: string) => void; setDescription: (v: string) => void; setReport: (v: Report) => void
}

const DeliveryContext = createContext<DeliveryState | null>(null)

export function DeliveryProvider({ children }: PropsWithChildren) {
  const [serviceOrderId, setServiceOrderIdState] = useState(() => Taro.getStorageSync<string>('ganwanleServiceOrderId') || '')
  const [remoteOrder, setRemoteOrder] = useState<ApiServiceOrder | null>(null)
  const [generatedReport, setGeneratedReportState] = useState<ApiGeneratedReport | null>(null)
  const [reportConfirmed, setReportConfirmed] = useState(false)
  const [beforePhotos, setBeforePhotos] = useState<string[]>([])
  const [afterPhotos, setAfterPhotos] = useState<string[]>([])
  const [voicePath, setVoicePath] = useState('')
  const [description, setDescription] = useState('')
  const [report, setReport] = useState<Report>(initialReport)
  const setServiceOrderId = (value: string) => { setServiceOrderIdState(value); value ? Taro.setStorageSync('ganwanleServiceOrderId', value) : Taro.removeStorageSync('ganwanleServiceOrderId') }
  const setGeneratedReport = (value: ApiGeneratedReport | null) => { setGeneratedReportState(value); setReportConfirmed(false) }
  const value = useMemo(() => ({ serviceOrderId, remoteOrder, generatedReport, reportConfirmed, beforePhotos, afterPhotos, voicePath, description, report,
    setServiceOrderId, setRemoteOrder, setGeneratedReport, setReportConfirmed,
    setBeforePhotos, setAfterPhotos, setVoicePath, setDescription, setReport
  }), [serviceOrderId, remoteOrder, generatedReport, reportConfirmed, beforePhotos, afterPhotos, voicePath, description, report])
  return <DeliveryContext.Provider value={value}>{children}</DeliveryContext.Provider>
}

export function useDelivery() {
  const value = useContext(DeliveryContext)
  if (!value) throw new Error('useDelivery must be used inside DeliveryProvider')
  return value
}
