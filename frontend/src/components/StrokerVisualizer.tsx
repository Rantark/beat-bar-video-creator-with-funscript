import type { EditAction } from './TimelineGraph'

/**
 * Vertical fill bar showing the interpolated funscript position at
 * `cursorMs`. Zero at the bottom, 100 at the top. Ticks every 25 units.
 *
 * Purely presentational — no interactivity — so it can sit beside the
 * video without stealing pointer events from anything else.
 */
export function StrokerVisualizer({
  actions,
  cursorMs,
}: {
  actions: EditAction[]
  cursorMs: number
}) {
  const pos = interpolate(actions, cursorMs)
  return (
    <div className="flex flex-col items-center gap-2 select-none">
      <div className="text-xs text-slate-400 font-mono">Pos</div>
      <div className="relative w-12 md:w-14 h-full min-h-[240px] flex-1 bg-slate-950 rounded-lg overflow-hidden border border-slate-700">
        <div
          className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-indigo-600 to-indigo-400 transition-[height] duration-100 ease-linear"
          style={{ height: `${pos}%` }}
        />
        {[25, 50, 75].map((p) => (
          <div
            key={p}
            className="absolute inset-x-0 h-px bg-slate-700/60 pointer-events-none"
            style={{ bottom: `${p}%` }}
          />
        ))}
        {[0, 50, 100].map((p) => (
          <span
            key={p}
            className="absolute left-1 text-[10px] text-slate-500 font-mono pointer-events-none"
            style={{ bottom: `${p}%`, transform: 'translateY(50%)' }}
          >
            {p}
          </span>
        ))}
        <div
          className="absolute inset-x-0 h-0.5 bg-white/80 pointer-events-none transition-[bottom] duration-100 ease-linear"
          style={{ bottom: `${pos}%` }}
        />
      </div>
      <div className="text-lg text-indigo-300 font-mono tabular-nums w-10 text-center">
        {pos}
      </div>
    </div>
  )
}

function interpolate(actions: EditAction[], t: number): number {
  if (actions.length === 0) return 50
  if (t <= actions[0].at) return actions[0].pos
  if (t >= actions[actions.length - 1].at) return actions[actions.length - 1].pos
  // Linear scan — funscripts rarely have >1000 actions and this is
  // called at video-frame rate at worst. Binary search is overkill.
  for (let i = 0; i < actions.length - 1; i++) {
    const a = actions[i]
    const b = actions[i + 1]
    if (t >= a.at && t <= b.at) {
      const span = b.at - a.at
      if (span <= 0) return b.pos
      const frac = (t - a.at) / span
      return Math.round(a.pos + frac * (b.pos - a.pos))
    }
  }
  return actions[actions.length - 1].pos
}
