import Taro from '@tarojs/taro'
import { act, create } from 'react-test-renderer'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SignaturePad from './index'

const canvasContext = {
  beginPath: vi.fn(),
  clearRect: vi.fn(),
  draw: vi.fn(),
  lineTo: vi.fn(),
  moveTo: vi.fn(),
  setLineCap: vi.fn(),
  setLineJoin: vi.fn(),
  setLineWidth: vi.fn(),
  setStrokeStyle: vi.fn(),
  stroke: vi.fn()
}

vi.mock('@tarojs/taro', () => ({
  default: { createCanvasContext: vi.fn(() => canvasContext) }
}))
vi.mock('@tarojs/components', () => ({ Button: 'button', Canvas: 'canvas', Text: 'text', View: 'view' }))
vi.mock('./index.scss', () => ({}))

describe('SignaturePad', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })

  afterEach(() => vi.useRealTimers())

  it('batches rapid touch points into one native canvas draw per frame', async () => {
    const onSignedChange = vi.fn()
    const renderer = create(<SignaturePad disabled={false} signed={false} onSignedChange={onSignedChange} />)
    const canvas = renderer.root.findByType('canvas')

    await act(async () => {
      canvas.props.onTouchStart({ changedTouches: [{ x: 10, y: 20 }] })
      canvas.props.onTouchMove({ changedTouches: [{ x: 11, y: 21 }] })
      canvas.props.onTouchMove({ changedTouches: [{ x: 12, y: 22 }] })
      canvas.props.onTouchMove({ changedTouches: [{ x: 13, y: 23 }] })
    })

    expect(canvasContext.draw).not.toHaveBeenCalled()
    expect(onSignedChange).toHaveBeenCalledTimes(1)

    await act(async () => vi.advanceTimersByTime(16))

    expect(canvasContext.moveTo).toHaveBeenCalledWith(10, 20)
    expect(canvasContext.lineTo).toHaveBeenCalledTimes(3)
    expect(canvasContext.stroke).toHaveBeenCalledTimes(1)
    expect(canvasContext.draw).toHaveBeenCalledTimes(1)
    expect(canvasContext.draw).toHaveBeenCalledWith(true)
  })

  it('flushes the final points when the finger leaves the canvas', async () => {
    const renderer = create(<SignaturePad disabled={false} signed={false} onSignedChange={vi.fn()} />)
    const canvas = renderer.root.findByType('canvas')

    await act(async () => {
      canvas.props.onTouchStart({ changedTouches: [{ x: 5, y: 6 }] })
      canvas.props.onTouchMove({ changedTouches: [{ x: 15, y: 16 }] })
      canvas.props.onTouchEnd()
    })

    expect(canvasContext.moveTo).toHaveBeenCalledWith(5, 6)
    expect(canvasContext.lineTo).toHaveBeenCalledWith(15, 16)
    expect(canvasContext.draw).toHaveBeenCalledWith(true)
    expect(vi.getTimerCount()).toBe(0)
  })
})
