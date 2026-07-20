/**
 * Preset beat patterns for audio-mode sections.
 *
 * Each pattern is a fixed-length array of on/off slots. When applied
 * to a section, the section's detected beat period drives one slot per
 * step — checked slots emit a stroke, unchecked slots skip. The backend
 * cycles the pattern across the whole section, so different sections
 * pick different patterns from this library and feel rhythmically
 * distinct even when the music holds one steady tempo.
 */

const SLOT_OPTIONS = [4, 6, 8, 10, 12, 14, 16] as const

export function BeatPatternEditor({
  patterns,
  onChange,
}: {
  patterns: boolean[][]
  onChange: (patterns: boolean[][]) => void
}) {
  function add() {
    // Default new pattern: 8 slots, every other slot on — a plain
    // half-time feel that reads as an obvious change from an off/off
    // starting state.
    const fresh = Array.from({ length: 8 }, (_, i) => i % 2 === 0)
    onChange([...patterns, fresh])
  }

  function remove(idx: number) {
    onChange(patterns.filter((_, i) => i !== idx))
  }

  function toggleSlot(patternIdx: number, slotIdx: number) {
    onChange(patterns.map((p, i) =>
      i === patternIdx
        ? p.map((v, j) => (j === slotIdx ? !v : v))
        : p
    ))
  }

  function resize(patternIdx: number, newLen: number) {
    onChange(patterns.map((p, i) => {
      if (i !== patternIdx) return p
      if (newLen === p.length) return p
      if (newLen > p.length) {
        // Grow: repeat the pattern into the new slots so the extension
        // reads as a natural continuation rather than off-padding.
        return Array.from({ length: newLen }, (_, j) => p[j % p.length])
      }
      return p.slice(0, newLen)
    }))
  }

  return (
    <div className="mt-5 pt-3 border-t border-slate-800">
      <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">
        Preset beat patterns
      </p>
      <p className="text-xs text-slate-500 mb-3">
        Add rhythms the algorithm will use inside sections. Each checked
        slot is a stroke at the section's detected tempo; unchecked slots
        skip. Leave empty for a continuous grid.
      </p>
      <p className="text-xs text-slate-500 mb-3">
        <span className="text-slate-400">Speed matching:</span> the
        algorithm scores each pattern by how many slots are on (density)
        and picks patterns that match the section's speed — fast
        sections favor dense patterns, slow sections favor sparse ones.
        Build a range from sparse to dense to get natural variety across
        a song's changes in energy.
      </p>
      <div className="flex flex-col gap-2">
        {patterns.map((p, i) => {
          const density = p.filter(Boolean).length / p.length
          const feel = density < 0.35 ? 'slow' : density > 0.65 ? 'fast' : 'medium'
          return (
          <div
            key={i}
            className="flex items-center gap-2 p-2 rounded bg-slate-900/60 border border-slate-800"
          >
            <span
              className="w-14 shrink-0 text-xs font-mono text-slate-400"
              title={`Density ${(density * 100).toFixed(0)}%`}
            >
              {feel}
            </span>
            <div className="flex flex-wrap gap-1 flex-1 min-w-0">
              {p.map((on, j) => (
                <button
                  key={j}
                  onClick={() => toggleSlot(i, j)}
                  className={`w-7 h-7 rounded text-xs font-mono border ${
                    on
                      ? 'bg-indigo-500 border-indigo-400 text-white'
                      : 'bg-slate-800 border-slate-700 text-slate-500'
                  }`}
                  title={`Slot ${j + 1}`}
                >
                  {on ? '●' : '·'}
                </button>
              ))}
            </div>
            <select
              value={p.length}
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
