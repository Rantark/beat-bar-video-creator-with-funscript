import type { Line } from '../types'
import { LINE_STRIP_FRACTION } from '../types'

/**
 * View-only overlay showing the finite line segment and the detection
 * strip around it. Non-interactive by design so it doesn't intercept
 * touches on the video; the line is edited via the sliders in the
 * FramePickerPage control panel.
 */
export function LineDrawer({ line }: { line: Line }) {
  const halfL = line.length / 2
  const halfStrip = LINE_STRIP_FRACTION / 2

  const strip =
    line.orientation === 'horizontal'
      ? {
          left: pct(line.x - halfL),
          top: pct(line.y - halfStrip),
          width: pct(line.length),
          height: pct(LINE_STRIP_FRACTION),
        }
      : {
          left: pct(line.x - halfStrip),
          top: pct(line.y - halfL),
          width: pct(LINE_STRIP_FRACTION),
          height: pct(line.length),
        }

  const segment =
    line.orientation === 'horizontal'
      ? {
          left: pct(line.x - halfL),
          top: pct(line.y),
          width: pct(line.length),
          height: '2px',
          marginTop: '-1px',
        }
      : {
          left: pct(line.x),
          top: pct(line.y - halfL),
          width: '2px',
          height: pct(line.length),
          marginLeft: '-1px',
        }

  return (
    <div className="absolute inset-0 pointer-events-none">
      <div
        className="absolute border border-emerald-400/40 bg-emerald-400/10"
        style={strip}
      />
      <div
        className="absolute bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.9)]"
        style={segment}
      />
    </div>
  )
}

function pct(v: number): string {
  return `${clamp01(v) * 100}%`
}
function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v))
}
