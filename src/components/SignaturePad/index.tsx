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
  const strokes = useRef<Point[][]>([])
  const activeStroke = useRef<Point[] | null>(null)
  const renderTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rendering = useRef(false)
  const renderQueued = useRef(false)
  const signedReported = useRef(signed)

  useEffect(() => {
    signedReported.current = signed
  }, [signed])

  useEffect(() => () => {
    if (renderTimer.current) clearTimeout(renderTimer.current)
  }, [])

  const getContext = () => {
    if (!context.current) {
      context.current = Taro.createCanvasContext('customerSignature')
    }
    return context.current
  }

  const pointFromEvent = (event: { changedTouches?: Array<{ x?: number; y?: number }> }): Point | null => {
    const touch = event.changedTouches?.[0]
    return touch && typeof touch.x === 'number' && typeof touch.y === 'number' ? { x: touch.x, y: touch.y } : null
  }

  const render = () => {
    if (renderTimer.current) clearTimeout(renderTimer.current)
    renderTimer.current = null
    if (rendering.current) {
      renderQueued.current = true
      return
    }
    rendering.current = true
    renderQueued.current = false
    const ctx = getContext()
    ctx.clearRect(0, 0, 1000, 500)
    ctx.setStrokeStyle('#173b65')
    ctx.setLineWidth(5)
    ctx.setLineCap('round')
    ctx.setLineJoin('round')
    strokes.current.forEach(stroke => {
      if (stroke.length < 2) return
      ctx.beginPath()
      ctx.moveTo(stroke[0].x, stroke[0].y)
      for (let index = 1; index < stroke.length - 1; index += 1) {
        const point = stroke[index]
        const nextPoint = stroke[index + 1]
        ctx.quadraticCurveTo(
          point.x,
          point.y,
          (point.x + nextPoint.x) / 2,
          (point.y + nextPoint.y) / 2
        )
      }
      const finalPoint = stroke[stroke.length - 1]
      ctx.lineTo(finalPoint.x, finalPoint.y)
      ctx.stroke()
    })
    ctx.draw(false, () => {
      rendering.current = false
      if (renderQueued.current) scheduleRender(0)
    })
  }

  const scheduleRender = (delay = 16) => {
    if (renderTimer.current) return
    renderTimer.current = setTimeout(render, delay)
  }

  const start = (event: { changedTouches?: Array<{ x?: number; y?: number }> }) => {
    if (disabled) return
    const point = pointFromEvent(event)
    if (!point) return
    drawing.current = true
    const stroke = [point]
    strokes.current.push(stroke)
    activeStroke.current = stroke
  }

  const move = (event: { changedTouches?: Array<{ x?: number; y?: number }> }) => {
    if (disabled || !drawing.current) return
    const point = pointFromEvent(event)
    if (!point || !activeStroke.current) return
    activeStroke.current.push(point)
    scheduleRender()
    if (!signedReported.current) {
      signedReported.current = true
      onSignedChange(true)
    }
  }

  const end = () => {
    drawing.current = false
    activeStroke.current = null
    render()
  }
  const clear = () => {
    if (disabled) return
    if (renderTimer.current) clearTimeout(renderTimer.current)
    renderTimer.current = null
    drawing.current = false
    activeStroke.current = null
    strokes.current = []
    renderQueued.current = true
    render()
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
