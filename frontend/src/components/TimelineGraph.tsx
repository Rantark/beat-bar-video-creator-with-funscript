import { useEffect, useRef, useState } from 'react'

export type EditAction = { id: string; at: number; pos: number }

type RubberBand = { at1: number; at2: number; pos1: number; pos2: number }

/**
 * SVG timeline. Selection is by stable IDs so re-sorting after a drag
 * doesn't invalidate the caller's selection set.
 *
 * Two modes:
 *   editMode (default) — tap point = select single, drag point = move
 *     just that point, tap empty = add point + seek.
 *   selectMode         — tap point = toggle in selection, drag point =
 *     move the whole selection by the same delta, drag empty = rubber-
 *     band select, tap empty = deselect + seek.
 */
export function TimelineGraph({
  actions,
  durationMs,
  pxPerSecond,
  cursorMs,
  selection,
  selectMode,
  onPointDown,
  onDragDelta,
  onDragEnd,
  onEmptyTap,
  onRubberBand,
  onZoomStep,
  sectionBoundariesMs,
}: {
  actions: EditAction[]
  durationMs: number
  pxPerSecond: number
  cursorMs: number
  selection: Set<string>
  selectMode: boolean
  onPointDown: (id: string) => void
  onDragDelta: (dtMs: number, dPos: number) => void
  onDragEnd: () => void
  onEmptyTap: (at_ms: number, pos: number) => void
  onRubberBand: (bounds: RubberBand) => void
  onZoomStep?: (direction: 1 | -1) => void
  // Vertical dividers drawn over the timeline (audio-mode sections).
  // Endpoints of the sections; the outer 0 and durationMs don't need to
  // be included but no harm if they are.
  sectionBoundariesMs?: number[]
}) {
  const HEIGHT = 200
  const PLOT_HEIGHT = HEIGHT - 24 // reserve strip at bottom for the time axis
  const width = Math.max(400, Math.round((durationMs / 1000) * pxPerSecond))
  const scrollerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  // Two mutually-exclusive drag kinds:
  //   pointDrag: dragging a selected point (or group)
  //   bandDrag:  drawing a rubber-band on the empty area
  const [pointDrag, setPointDrag] = useState<null | {
    startX: number
    startY: number
  }>(null)
  const [bandDrag, setBandDrag] = useState<null | {
    startX: number
    startY: number
    curX: number
    curY: number
  }>(null)

  useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    const cursorX = (cursorMs / 1000) * pxPerSecond
    const view = el.clientWidth
    const scroll = el.scrollLeft
    if (cursorX < scroll + view * 0.15 || cursorX > scroll + view * 0.85) {
      el.scrollTo({ left: Math.max(0, cursorX - view / 2), behavior: 'smooth' })
    }
  }, [cursorMs, pxPerSecond])

  function localXY(clientX: number, clientY: number) {
    const rect = svgRef.current!.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(width, clientX - rect.left)),
      y: Math.max(0, Math.min(HEIGHT, clientY - rect.top)),
    }
  }
  const xToMs = (x: number) => Math.max(0, Math.round((x / pxPerSecond) * 1000))
  const yToPos = (y: number) =>
    Math.max(0, Math.min(100, Math.round(100 - (y / PLOT_HEIGHT) * 100)))
  const atToX = (at: number) => (at / 1000) * pxPerSecond
  const posToY = (pos: number) => (1 - pos / 100) * PLOT_HEIGHT

  function onPointPointerDown(id: string) {
    return (e: React.PointerEvent) => {
      e.stopPropagation()
      ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
      onPointDown(id)
      setPointDrag({ startX: e.clientX, startY: e.clientY })
    }
  }

  function onSvgPointerDown(e: React.PointerEvent) {
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    const { x, y } = localXY(e.clientX, e.clientY)
    if (selectMode) {
      // Empty-area interaction in select mode: could be tap-to-deselect
      // (short) or rubber-band (long). Kick off band, decide on release.
      setBandDrag({ startX: e.clientX, startY: e.clientY, curX: e.clientX, curY: e.clientY })
    } else {
      // Edit mode: track potential add-point on release.
      setBandDrag({ startX: e.clientX, startY: e.clientY, curX: e.clientX, curY: e.clientY })
      // We don't emit anything yet — differentiate tap vs. drag on release.
      void x
      void y
    }
  }

  function onSvgPointerMove(e: React.PointerEvent) {
    if (pointDrag) {
      const dx = e.clientX - pointDrag.startX
      const dy = e.clientY - pointDrag.startY
      const dtMs = Math.round((dx / pxPerSecond) * 1000)
      const dPos = -Math.round((dy / PLOT_HEIGHT) * 100)
      onDragDelta(dtMs, dPos)
    } else if (bandDrag) {
      setBandDrag({ ...bandDrag, curX: e.clientX, curY: e.clientY })
    }
  }

  function onSvgPointerUp(e: React.PointerEvent) {
    if (pointDrag) {
      setPointDrag(null)
      onDragEnd()
      return
    }
    if (bandDrag) {
      const dx = bandDrag.curX - bandDrag.startX
      const dy = bandDrag.curY - bandDrag.startY
      const moved = Math.hypot(dx, dy) > 6
      const { x, y } = localXY(e.clientX, e.clientY)
      if (!moved) {
        onEmptyTap(xToMs(x), yToPos(Math.min(y, PLOT_HEIGHT)))
      } else if (selectMode) {
        const a = localXY(bandDrag.startX, bandDrag.startY)
        const b = localXY(e.clientX, e.clientY)
        const at1 = xToMs(Math.min(a.x, b.x))
        const at2 = xToMs(Math.max(a.x, b.x))
        const pos1 = yToPos(Math.max(a.y, b.y))
        const pos2 = yToPos(Math.min(a.y, b.y))
        onRubberBand({ at1, at2, pos1, pos2 })
      }
      setBandDrag(null)
    }
  }

  const cursorX = atToX(cursorMs)

  // Rubber-band rectangle in SVG coords
  let bandRect: {
    x: number
    y: number
    w: number
    h: number
  } | null = null
  if (bandDrag && selectMode) {
    const a = localXY(bandDrag.startX, bandDrag.startY)
    const b = localXY(bandDrag.curX, bandDrag.curY)
    if (Math.hypot(b.x - a.x, b.y - a.y) > 4) {
      bandRect = {
        x: Math.min(a.x, b.x),
        y: Math.min(a.y, b.y),
        w: Math.abs(b.x - a.x),
        h: Math.abs(b.y - a.y),
      }
    }
  }

  function onWheel(e: React.WheelEvent) {
    // Ctrl/⌘ + wheel = zoom timeline (standard desktop convention). A
    // plain wheel is left alone so the container can scroll horizontally.
    if (!(e.ctrlKey || e.metaKey) || !onZoomStep) return
    e.preventDefault()
    e.stopPropagation()
    onZoomStep(e.deltaY < 0 ? 1 : -1)
  }

  return (
    <div className="w-full">
      <div
        ref={scrollerRef}
        onWheel={onWheel}
        className="w-full overflow-x-auto overflow-y-hidden bg-slate-900 border-y border-slate-800 select-none"
      >
        <svg
          ref={svgRef}
          width={width}
          height={HEIGHT}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          className="block touch-none"
          onPointerDown={onSvgPointerDown}
          onPointerMove={onSvgPointerMove}
          onPointerUp={onSvgPointerUp}
          onPointerCancel={onSvgPointerUp}
        >
          {[0.25, 0.5, 0.75].map((r) => (
            <line
              key={r}
              x1={0}
              y1={PLOT_HEIGHT * r}
              x2={width}
              y2={PLOT_HEIGHT * r}
              stroke="rgba(255,255,255,0.07)"
              strokeWidth={1}
            />
          ))}
          {sectionBoundariesMs?.map((ms, i) => (
            <line
              key={`sec-${i}`}
              x1={atToX(ms)}
              y1={0}
              x2={atToX(ms)}
              y2={HEIGHT - 20}
              stroke="rgba(251, 191, 36, 0.5)"
              strokeWidth={1}
              strokeDasharray="4 3"
            />
          ))}
          {Array.from({ length: Math.ceil(durationMs / 1000) + 1 }).map((_, s) => {
            const x = s * pxPerSecond
            const isTen = s % 10 === 0
            return (
              <g key={s}>
                <line
                  x1={x}
                  y1={HEIGHT - (isTen ? 12 : 6)}
                  x2={x}
                  y2={HEIGHT}
                  stroke={isTen ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.15)'}
                  strokeWidth={1}
                />
                {isTen && (
                  <text
                    x={x + 3}
                    y={HEIGHT - 3}
                    fill="rgba(255,255,255,0.5)"
                    fontSize={10}
                  >
                    {s}s
                  </text>
                )}
              </g>
            )
          })}

          {actions.length > 1 && (
            <polyline
              points={actions
                .map((a) => `${atToX(a.at)},${posToY(a.pos)}`)
                .join(' ')}
              fill="none"
              stroke="rgb(99,102,241)"
              strokeWidth={2}
            />
          )}

          {actions.map((a) => {
            const cx = atToX(a.at)
            const cy = posToY(a.pos)
            const isSel = selection.has(a.id)
            return (
              <circle
                key={a.id}
                cx={cx}
                cy={cy}
                r={isSel ? 9 : 6}
                fill={isSel ? 'rgb(250,204,21)' : 'rgb(129,140,248)'}
                stroke={isSel ? 'rgb(250,204,21)' : 'rgba(0,0,0,0.4)'}
                strokeWidth={isSel ? 3 : 1}
                onPointerDown={onPointPointerDown(a.id)}
                style={{ cursor: 'pointer' }}
              />
            )
          })}

          {bandRect && (
            <rect
              x={bandRect.x}
              y={bandRect.y}
              width={bandRect.w}
              height={bandRect.h}
              fill="rgba(250,204,21,0.08)"
              stroke="rgb(250,204,21)"
              strokeDasharray="4 3"
              strokeWidth={1}
              pointerEvents="none"
            />
          )}

          <line
            x1={cursorX}
            y1={0}
            x2={cursorX}
            y2={HEIGHT}
            stroke="rgb(239,68,68)"
            strokeWidth={2}
            pointerEvents="none"
          />
        </svg>
      </div>
    </div>
  )
}
