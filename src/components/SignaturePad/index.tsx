import Taro from '@tarojs/taro'
import { Button, Canvas, Text, View } from '@tarojs/components'
import { useEffect, useRef } from 'react'
import './index.scss'

type Point = { x: number; y: number }
type SignaturePadProps = {
  disabled: boolean
  signed: boolean
  onSignedChange: (signed: boolean) => void
}

export default function SignaturePad({ disabled, signed, onSignedChange }: SignaturePadProps) {
  const context = useRef<Taro.CanvasContext | null>(null)
  const drawing = useRef(false)
  const lastPoint = useRef<Point | null>(null)
  const pendingPoints = useRef<Point[]>([])
  const flushTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const signedReported = useRef(signed)

  useEffect(() => {
    signedReported.current = signed
  }, [signed])

  useEffect(() => () => {
    if (flushTimer.current) clearTimeout(flushTimer.current)
  }, [])

  const getContext = () => {
    if (!context.current) {
      context.current = Taro.createCanvasContext('customerSignature')
      context.current.setStrokeStyle('#173b65')
      context.current.setLineWidth(4)
      context.current.setLineCap('round')
      context.current.setLineJoin('round')
    }
    return context.current
  }

  const pointFromEvent = (event: { changedTouches?: Array<{ x?: number; y?: number }> }): Point | null => {
    const touch = event.changedTouches?.[0]
    return touch && typeof touch.x === 'number' && typeof touch.y === 'number' ? { x: touch.x, y: touch.y } : null
  }

  const flush = () => {
    if (flushTimer.current) clearTimeout(flushTimer.current)
    flushTimer.current = null
    const startPoint = lastPoint.current
    const points = pendingPoints.current.splice(0)
    if (!startPoint || !points.length) return
    const ctx = getContext()
    ctx.beginPath()
    ctx.moveTo(startPoint.x, startPoint.y)
    points.forEach(point => ctx.lineTo(point.x, point.y))
    ctx.stroke()
    ctx.draw(true)
    lastPoint.current = points[points.length - 1]
  }

  const scheduleFlush = () => {
    if (flushTimer.current) return
    flushTimer.current = setTimeout(flush, 16)
  }

  const start = (event: { changedTouches?: Array<{ x?: number; y?: number }> }) => {
    if (disabled) return
    const point = pointFromEvent(event)
    if (!point) return
    flush()
    drawing.current = true
    lastPoint.current = point
  }

  const move = (event: { changedTouches?: Array<{ x?: number; y?: number }> }) => {
    if (disabled || !drawing.current) return
    const point = pointFromEvent(event)
    if (!point) return
    pendingPoints.current.push(point)
    scheduleFlush()
    if (!signedReported.current) {
      signedReported.current = true
      onSignedChange(true)
    }
  }

  const end = () => {
    drawing.current = false
    flush()
    lastPoint.current = null
  }
  const clear = () => {
    if (disabled) return
    if (flushTimer.current) clearTimeout(flushTimer.current)
    flushTimer.current = null
    drawing.current = false
    lastPoint.current = null
    pendingPoints.current = []
    const ctx = getContext()
    ctx.clearRect(0, 0, 1000, 500)
    ctx.draw()
    signedReported.current = false
    onSignedChange(false)
  }

  return <View className='signature-wrap'>
    <View className={`signature-canvas-wrap ${disabled ? 'disabled' : ''}`}>
      {!signed && <Text className='signature-placeholder'>请在此处签名</Text>}
      <Canvas
        className='signature-canvas'
        canvasId='customerSignature'
        id='customerSignature'
        disableScroll
        onTouchStart={start}
        onTouchMove={move}
        onTouchEnd={end}
        onTouchCancel={end}
      />
    </View>
    {!disabled && <Button className='clear-signature' onClick={clear}>清除重签</Button>}
  </View>
}
