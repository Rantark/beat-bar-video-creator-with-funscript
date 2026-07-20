import { useRef, useState } from 'react'
import type { Zone } from '../types'

/**
 * Touch-drag on the video draws a rectangle in normalized [0..1] coords.
 * Normalized coords make params independent of display size and video
 * resolution — the backend can multiply by the source width/height.
 * Uses pointer events for one unified path across touch and mouse.
 */
export function ZoneDrawer({
  zone,
  onChange,
}: {
  zone: Zone | null
  onChange: (z: Zone | null) => void
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<{ sx: number; sy: number } | null>(null)

  function coords(e: React.PointerEvent) {
    const rect = boxRef.current!.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    }
  }

  return (
    <div
      ref={boxRef}
      className="absolute inset-0 touch-none cursor-crosshair"
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        const c = coords(e)
        setDrag({ sx: c.x, sy: c.y })
        onChange({ x: c.x, y: c.y, w: 0, h: 0 })
      }}
      onPointerMove={(e) => {
        if (!drag) return
        const c = coords(e)
        onChange({
          x: Math.min(drag.sx, c.x),
          y: Math.min(drag.sy, c.y),
          w: Math.abs(c.x - drag.sx),
          h: Math.abs(c.y - drag.sy),
        })
      }}
      onPointerUp={() => setDrag(null)}
    >
      {zone && zone.w > 0 && zone.h > 0 && (
        <div
          className="absolute border-2 border-indigo-400 bg-indigo-400/20 pointer-events-none"
          style={{
            left: `${zone.x * 100}%`,
            top: `${zone.y * 100}%`,
            width: `${zone.w * 100}%`,
            height: `${zone.h * 100}%`,
          }}
        />
      )}
    </div>
  )
}
