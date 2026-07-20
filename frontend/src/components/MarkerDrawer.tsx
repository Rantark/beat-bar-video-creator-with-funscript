import { useEffect, useRef, useState } from 'react'
import type { Marker } from '../types'

// Only touch inputs benefit from the magnifier. A mouse cursor is
// already pixel-accurate, so the loupe just gets in the way there.
const isCoarsePointer =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(pointer: coarse)').matches

/**
 * Touch to place/drag the hit-point circle. While a finger is down,
 * shows a magnifier loupe with a crosshair so you can pixel-place the
 * marker on a phone. Uses pointer events so the same code path handles
 * touch and mouse.
 *
 * Marker coords are stored normalized: (x, y) in [0..1] of the video's
 * display box, radius as a fraction of the smaller video dimension so
 * the on-screen size is display-scale-independent.
 */
export function MarkerDrawer({
  marker,
  onChange,
  videoRef,
  videoDims,
}: {
  marker: Marker
  onChange: (m: Marker) => void
  videoRef: React.RefObject<HTMLVideoElement | null>
  videoDims: { width: number; height: number }
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)
  const [screenPos, setScreenPos] = useState<{ x: number; y: number } | null>(null)
  const snapshotRef = useRef<HTMLCanvasElement | null>(null)
  // Bumped after captureFrame's async draw completes so the loupe
  // component re-renders with the fresh snapshot instead of blank.
  const [snapshotVersion, setSnapshotVersion] = useState(0)

  async function captureFrame() {
    const video = videoRef.current
    if (!video || video.videoWidth === 0) return
    // Firefox in particular doesn't decode any frames until played or
    // seeked past the current time. If readyState < HAVE_CURRENT_DATA
    // (2), drawImage will produce a black canvas — force a micro-seek
    // and wait for the resulting `seeked` event so the frame is decoded.
    if (video.readyState < 2) {
      const t = video.currentTime
      await new Promise<void>((resolve) => {
        const done = () => {
          video.removeEventListener('seeked', done)
          video.removeEventListener('loadeddata', done)
          resolve()
        }
        video.addEventListener('seeked', done, { once: true })
        video.addEventListener('loadeddata', done, { once: true })
        // Nudge the currentTime by 1ms to trigger a seek — falls back to
        // waiting for `loadeddata` if that isn't allowed yet.
        try { video.currentTime = t + 0.001 } catch { /* ignore */ }
        // Belt and braces: bail after 300ms so a broken stream doesn't
        // hang the loupe.
        window.setTimeout(done, 300)
      })
      if (video.videoWidth === 0) return
    }
    if (!snapshotRef.current) snapshotRef.current = document.createElement('canvas')
    const c = snapshotRef.current
    c.width = video.videoWidth
    c.height = video.videoHeight
    try {
      c.getContext('2d')!.drawImage(video, 0, 0)
      setSnapshotVersion((n) => n + 1)
    } catch { /* browser refused — loupe will show black; that's OK */ }
  }

  function toNorm(e: React.PointerEvent) {
    const rect = boxRef.current!.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    }
  }

  function onDown(e: React.PointerEvent) {
    e.currentTarget.setPointerCapture(e.pointerId)
    captureFrame()
    setDragging(true)
    const n = toNorm(e)
    onChange({ ...marker, x: n.x, y: n.y })
    setScreenPos({ x: e.clientX, y: e.clientY })
  }
  function onMove(e: React.PointerEvent) {
    if (!dragging) return
    const n = toNorm(e)
    onChange({ ...marker, x: n.x, y: n.y })
    setScreenPos({ x: e.clientX, y: e.clientY })
  }
  function onUp() {
    setDragging(false)
    setScreenPos(null)
  }

  // Radius in SVG viewBox units (video pixels)
  const rSvg = marker.radius * Math.min(videoDims.width, videoDims.height)
  const cxSvg = marker.x * videoDims.width
  const cySvg = marker.y * videoDims.height

  return (
    <>
      <div
        ref={boxRef}
        className="absolute inset-0 touch-none cursor-crosshair"
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
      >
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none"
          viewBox={`0 0 ${videoDims.width} ${videoDims.height}`}
          preserveAspectRatio="none"
        >
          <circle
            cx={cxSvg}
            cy={cySvg}
            r={rSvg}
            fill="rgba(250,204,21,0.18)"
            stroke="rgb(250,204,21)"
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
          <line
            x1={cxSvg - rSvg * 0.6} y1={cySvg}
            x2={cxSvg + rSvg * 0.6} y2={cySvg}
            stroke="rgb(250,204,21)" strokeWidth={1}
            vectorEffect="non-scaling-stroke"
          />
          <line
            x1={cxSvg} y1={cySvg - rSvg * 0.6}
            x2={cxSvg} y2={cySvg + rSvg * 0.6}
            stroke="rgb(250,204,21)" strokeWidth={1}
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>
      {isCoarsePointer && screenPos && snapshotRef.current && (
        <LoupeOverlay
          snapshot={snapshotRef.current}
          snapshotVersion={snapshotVersion}
          markerX={marker.x}
          markerY={marker.y}
          screenX={screenPos.x}
          screenY={screenPos.y}
        />
      )}
    </>
  )
}

function LoupeOverlay({
  snapshot,
  snapshotVersion,
  markerX,
  markerY,
  screenX,
  screenY,
}: {
  snapshot: HTMLCanvasElement
  snapshotVersion: number
  markerX: number
  markerY: number
  screenX: number
  screenY: number
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const size = 120
  const zoom = 4

  useEffect(() => {
    const c = canvasRef.current
    if (!c || snapshot.width === 0) return
    c.width = size
    c.height = size
    const ctx = c.getContext('2d')!
    ctx.imageSmoothingEnabled = false
    ctx.fillStyle = '#000'
    ctx.fillRect(0, 0, size, size)
    // Sample a size/zoom-pixel window from the snapshot, centered on marker
    const srcSize = size / zoom
    const srcX = markerX * snapshot.width - srcSize / 2
    const srcY = markerY * snapshot.height - srcSize / 2
    ctx.drawImage(snapshot, srcX, srcY, srcSize, srcSize, 0, 0, size, size)
    // Crosshair at center
    ctx.strokeStyle = 'rgb(250,204,21)'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(size / 2, 0); ctx.lineTo(size / 2, size)
    ctx.moveTo(0, size / 2); ctx.lineTo(size, size / 2)
    ctx.stroke()
    // snapshotVersion in deps forces a redraw when the parent finishes an
    // async captureFrame — the canvas is mutated in place, so React
    // otherwise has no way to know new pixels landed.
  }, [snapshot, snapshotVersion, markerX, markerY])

  // Position the loupe near-but-offset from the finger so it doesn't
  // sit under it. Bias upward so it stays visible on the phone screen.
  const OFFSET = 40
  const left = Math.max(8, Math.min(window.innerWidth - size - 8, screenX + OFFSET))
  const top = Math.max(8, screenY - size - OFFSET)

  return (
    <div
      className="fixed pointer-events-none border-2 border-yellow-400 rounded-full overflow-hidden bg-black shadow-lg"
      style={{ left, top, width: size, height: size, zIndex: 50 }}
    >
      <canvas ref={canvasRef} className="block" />
    </div>
  )
}
