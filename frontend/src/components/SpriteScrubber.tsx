import { useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { VideoMeta } from '../types'
import { fmtMs } from '../util'

/**
 * Touch-first scrubber. Live sprite thumb floats above the finger while
 * dragging — no video seek until release, so mobile scrubbing stays
 * responsive even on slow decoders.
 */
export function SpriteScrubber({
  video,
  onSeek,
}: {
  video: VideoMeta
  onSeek: (ms: number) => void
}) {
  const barRef = useRef<HTMLDivElement>(null)
  const [thumbIdx, setThumbIdx] = useState(0)
  const [previewMs, setPreviewMs] = useState(0)
  const [dragging, setDragging] = useState(false)

  const cols = video.sprite_cols ?? 1
  const rows = video.sprite_rows ?? 1
  const tw = video.sprite_thumb_width ?? 160
  const th = video.sprite_thumb_height ?? 90
  const interval = video.sprite_interval_ms ?? 1000
  const totalThumbs = useMemo(
    () => Math.max(1, Math.floor(video.duration_ms / interval) + 1),
    [video.duration_ms, interval],
  )

  function pointerRatio(e: React.PointerEvent) {
    const rect = barRef.current!.getBoundingClientRect()
    const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left))
    return rect.width > 0 ? x / rect.width : 0
  }

  function updateFromRatio(ratio: number) {
    const ms = Math.round(ratio * video.duration_ms)
    const idx = Math.min(totalThumbs - 1, Math.floor(ratio * totalThumbs))
    setThumbIdx(idx)
    setPreviewMs(ms)
  }

  const col = thumbIdx % cols
  const row = Math.floor(thumbIdx / cols)

  return (
    <div className="mt-3 select-none">
      <div className="flex justify-center mb-2">
        <div
          className="border border-slate-700 rounded overflow-hidden"
          style={{
            width: tw,
            height: th,
            backgroundImage: `url(${api.spriteUrl(video.id)})`,
            backgroundPosition: `-${col * tw}px -${row * th}px`,
            backgroundSize: `${cols * tw}px ${rows * th}px`,
          }}
        />
      </div>
      <div
        ref={barRef}
        className="w-full h-12 bg-slate-800 rounded-lg relative touch-none"
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId)
          setDragging(true)
          updateFromRatio(pointerRatio(e))
        }}
        onPointerMove={(e) => {
          if (dragging) updateFromRatio(pointerRatio(e))
        }}
        onPointerUp={() => {
          onSeek(previewMs)
          setDragging(false)
        }}
      >
        <div
          className="absolute top-0 h-12 bg-indigo-500/70 rounded-lg pointer-events-none"
          style={{
            width: `${(thumbIdx / Math.max(1, totalThumbs - 1)) * 100}%`,
          }}
        />
      </div>
      <div className="text-center text-sm text-slate-400 mt-1 font-mono">
        {fmtMs(previewMs)} / {fmtMs(video.duration_ms)}
      </div>
    </div>
  )
}
