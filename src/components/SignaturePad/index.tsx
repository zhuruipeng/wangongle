import Taro from '@tarojs/taro'
import { Button, Canvas, Text, View } from '@tarojs/components'
import { useRef } from 'react'
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

  const start = (event: { changedTouches?: Array<{ x?: number; y?: number }> }) => {
    if (disabled) return
    const point = pointFromEvent(event)
    if (!point) return
    drawing.current = true
    const ctx = getContext()
    ctx.beginPath()
    ctx.moveTo(point.x, point.y)
  }

  const move = (event: { changedTouches?: Array<{ x?: number; y?: number }> }) => {
    if (disabled || !drawing.current) return
    const point = pointFromEvent(event)
    if (!point) return
    const ctx = getContext()
    ctx.lineTo(point.x, point.y)
    ctx.stroke()
    ctx.draw(true)
    if (!signed) onSignedChange(true)
  }

  const end = () => { drawing.current = false }
  const clear = () => {
    if (disabled) return
    const ctx = getContext()
    ctx.clearRect(0, 0, 1000, 500)
    ctx.draw()
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
