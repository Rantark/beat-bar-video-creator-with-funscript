import { useState } from 'react'
import type { BeatPattern, PatternSlot } from '../types'

/**
 * Preset beat patterns with per-slot stroke depth.
 *
 * Each pattern is a fixed-length array of slots. Every slot carries
 * its own on/off flag plus a max_up / max_down depth pair, so a single
 * pattern can mix shallow accent beats with deep drop beats. The
 * backend cycles the pattern across the section at the detected
 * period; for each ON slot it emits a beat trough at slot.max_down
 * and a midpoint peak at slot.max_up. OFF slots are skipped.
 */

const SLOT_OPTIONS = [4, 6, 8, 10, 12, 14, 16] as const

function defaultSlot(on: boolean = false): PatternSlot {
  return { on, max_up: 100, max_down: 0 }
}

function defaultPattern(): BeatPattern {
  return {
    slots: Array.from({ length: 8 }, (_, i) => defaultSlot(i % 2 === 0)),
  }
}

export function BeatPatternEditor({
  patterns,
  onChange,
}: {
  patterns: BeatPattern[]
  onChange: (patterns: BeatPattern[]) => void
}) {
  // Which pattern rows are showing per-slot depth editors.
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  function toggleExpanded(idx: number) {
    const next = new Set(expanded)
    if (next.has(idx)) next.delete(idx)
    else next.add(idx)
    setExpanded(next)
  }

  function add() {
    onChange([...patterns, defaultPattern()])
  }

  function remove(idx: number) {
    onChange(patterns.filter((_, i) => i !== idx))
    setExpanded((prev) => {
      const next = new Set<number>()
      prev.forEach((i) => { if (i < idx) next.add(i); else if (i > idx) next.add(i - 1) })
      return next
    })
  }

  function toggleSlot(patternIdx: number, slotIdx: number) {
    onChange(patterns.map((p, i) =>
      i === patternIdx
        ? { ...p, slots: p.slots.map((s, j) => j === slotIdx ? { ...s, on: !s.on } : s) }
        : p
    ))
  }

  function updateSlot(patternIdx: number, slotIdx: number, patch: Partial<PatternSlot>) {
    onChange(patterns.map((p, i) => {
      if (i !== patternIdx) return p
      return {
        ...p,
        slots: p.slots.map((s, j) => j === slotIdx ? clampSlot({ ...s, ...patch }) : s),
      }
    }))
  }

  function resize(patternIdx: number, newLen: number) {
    onChange(patterns.map((p, i) => {
      if (i !== patternIdx) return p
      const cur = p.slots
      if (newLen === cur.length) return p
      if (newLen > cur.length) {
        // Grow by cloning existing slots (repeat) so the extension
        // reads as a natural continuation of the pattern.
        const grown = Array.from({ length: newLen }, (_, j) => ({ ...cur[j % cur.length] }))
        return { ...p, slots: grown }
      }
      return { ...p, slots: cur.slice(0, newLen) }
    }))
  }

  return (
    <div className="mt-5 pt-3 border-t border-slate-800">
      <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">
        Preset beat patterns
      </p>
      <p className="text-xs text-slate-500 mb-3">
        Add rhythms the algorithm will use inside sections. Each checked
        slot is a stroke at the section's detected tempo; unchecked
        slots skip. Every slot has its own depth (max_down = trough,
        max_up = midpoint peak) so a single pattern can mix shallow and
        deep strokes. Click ▸ on a pattern to edit per-slot depth.
      </p>
      <p className="text-xs text-slate-500 mb-3">
        <span className="text-slate-400">Speed matching:</span> the
        algorithm scores each pattern by how many slots are on (density)
        and picks patterns that match the section's speed — fast
        sections favor dense patterns, slow sections favor sparse ones.
      </p>
      <div className="flex flex-col gap-2">
        {patterns.map((p, i) => {
          const onCount = p.slots.filter((s) => s.on).length
          const density = onCount / Math.max(1, p.slots.length)
          const feel = density < 0.35 ? 'slow' : density > 0.65 ? 'fast' : 'medium'
          const isExpanded = expanded.has(i)
          return (
            <div
              key={i}
              className="p-2 rounded bg-slate-900/60 border border-slate-800"
            >
              <div className="flex items-center gap-2">
                <button
                  onClick={() => toggleExpanded(i)}
                  className="w-6 h-6 shrink-0 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs"
                  title={isExpanded ? 'Hide per-slot depth' : 'Edit per-slot depth'}
                >
                  {isExpanded ? '▾' : '▸'}
                </button>
                <span
                  className="w-14 shrink-0 text-xs font-mono text-slate-400"
                  title={`Density ${(density * 100).toFixed(0)}%`}
                >
                  {feel}
                </span>
                <div className="flex flex-wrap gap-1 flex-1 min-w-0">
                  {p.slots.map((slot, j) => (
                    <SlotButton
                      key={j}
                      slot={slot}
                      onClick={() => toggleSlot(i, j)}
                      title={
                        slot.on
                          ? `Slot ${j + 1}: down ${slot.max_down}, up ${slot.max_up}`
                          : `Slot ${j + 1}: skip`
                      }
                    />
                  ))}
                </div>
                <select
                  value={p.slots.length}
                  onChange={(e) => resize(i, parseInt(e.target.value, 10))}
                  className="bg-slate-800 border border-slate-700 rounded px-1 py-1 text-xs"
                  title="Number of slots"
                >
                  {SLOT_OPTIONS.map((n) => (
                    <option key={n} value={n}>{n} slots</option>
                  ))}
                </select>
                <button
                  onClick={() => remove(i)}
                  className="px-2 py-1 rounded text-xs bg-red-900/60 hover:bg-red-900 text-red-100"
                  title="Delete pattern"
                >
                  ×
                </button>
              </div>
              {isExpanded && (
                <div className="mt-2 pt-2 border-t border-slate-800">
                  <p className="text-xs text-slate-500 mb-2">
                    Per-slot depth. Down = trough (beat lands here). Up
                    = midpoint peak between this beat and the next.
                    Skipped slots are greyed.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {p.slots.map((slot, j) => (
                      <div
                        key={j}
                        className={`flex flex-col items-center gap-1 p-1 rounded border ${
                          slot.on
                            ? 'border-slate-700 bg-slate-900'
                            : 'border-slate-800 bg-slate-900/40 opacity-50'
                        }`}
                      >
                        <span className="text-[10px] font-mono text-slate-500">
                          #{j + 1}
                        </span>
                        <label className="flex flex-col items-center text-[10px] text-slate-400">
                          <span>up</span>
                          <input
                            type="number" min={0} max={100}
                            value={slot.max_up}
                            disabled={!slot.on}
                            onChange={(e) => updateSlot(i, j, {
                              max_up: parseInt(e.target.value, 10) || 0,
                            })}
                            className="w-12 bg-slate-800 border border-slate-700 rounded px-1 py-0.5 font-mono text-xs text-center disabled:opacity-50"
                          />
                        </label>
                        <label className="flex flex-col items-center text-[10px] text-slate-400">
                          <span>down</span>
                          <input
                            type="number" min={0} max={100}
                            value={slot.max_down}
                            disabled={!slot.on}
                            onChange={(e) => updateSlot(i, j, {
                              max_down: parseInt(e.target.value, 10) || 0,
                            })}
                            className="w-12 bg-slate-800 border border-slate-700 rounded px-1 py-0.5 font-mono text-xs text-center disabled:opacity-50"
                          />
                        </label>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })}
        <button
          onClick={add}
          className="self-start px-3 py-1.5 rounded text-sm bg-slate-700 hover:bg-slate-600"
        >
          + Add pattern
        </button>
      </div>
    </div>
  )
}

function SlotButton({
  slot,
  onClick,
  title,
}: {
  slot: PatternSlot
  onClick: () => void
  title: string
}) {
  if (!slot.on) {
    return (
      <button
        onClick={onClick}
        title={title}
        className="w-7 h-7 rounded text-xs font-mono border bg-slate-800 border-slate-700 text-slate-500"
      >
        ·
      </button>
    )
  }
  // Visualize depth as a tiny fill bar so the user can tell at a glance
  // which slots are shallow vs deep without expanding the row.
  const top = 100 - slot.max_up
  const height = Math.max(3, slot.max_up - slot.max_down)
  return (
    <button
      onClick={onClick}
      title={title}
      className="relative w-7 h-7 rounded text-xs font-mono border bg-indigo-500 border-indigo-400 text-white overflow-hidden"
    >
      <span
        className="absolute inset-x-0 bg-indigo-900/70 pointer-events-none"
        style={{ top: `${top}%`, height: `${height}%` }}
      />
      <span className="relative">●</span>
    </button>
  )
}

function clampSlot(s: PatternSlot): PatternSlot {
  const up = Math.max(0, Math.min(100, s.max_up))
  const down = Math.max(0, Math.min(100, s.max_down))
  // Allow up == down (single-position hold), but never up < down —
  // that would flip the stroke direction on that slot.
  return {
    on: s.on,
    max_up: Math.max(down, up),
    max_down: down,
  }
}
