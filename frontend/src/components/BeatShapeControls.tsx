/**
 * Shared shape / musical / motion / detection knobs used by both
 * marker and line modes. Both modes produce a list of beat timestamps
 * and feed them through the same beat_actions pipeline on the backend,
 * so they share the same downstream knobs.
 *
 * The parent owns the state; this component is a controlled view. Line
 * mode leaves `sensitivity` undefined (its detection uses a different
 * knob, exposed by the line panel itself).
 */
type Shape = {
  max_up: number
  max_up_fast: number
  max_down_fast: number
  max_down: number
  variety_amount: number
  idle_enabled: boolean
  motion_smoothing: number
  sensitivity?: number   // marker-only
}

export function BeatShapeControls({
  value,
  onChange,
  showSensitivity,
}: {
  value: Shape
  onChange: (patch: Partial<Shape>) => void
  showSensitivity: boolean
}) {
  return (
    <>
      <div className="mt-5 pt-3 border-t border-slate-800">
        <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">
          Detection & motion
        </p>
        {showSensitivity && value.sensitivity !== undefined && (
          <>
            <SliderRow
              label="Beat sensitivity"
              value={value.sensitivity}
              onChange={(v) => onChange({ sensitivity: v })}
            />
            <p className="mt-1 text-xs text-slate-500">
              Higher = catches fainter beats but risks noise. 0.5 = default;
              raise if beats are being missed, lower if extra strokes appear
              between real beats.
            </p>
          </>
        )}
        <SliderRow
          label="Motion smoothing"
          value={value.motion_smoothing / 4}
          onChange={(v) => onChange({ motion_smoothing: Math.round(v * 4) })}
        />
        <p className="mt-1 text-xs text-slate-500">
          Interpolation shape between beats. 0 = raw triangle (jerky
          reversals). 2-3 = S-curve so the toy accelerates and
          decelerates gently around each beat. Currently: level {value.motion_smoothing}.
        </p>
      </div>

      <div className="mt-5 pt-3 border-t border-slate-800">
        <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">
          Stroke shape
        </p>
        <SliderRow
          label="Max up — slow strokes (peak)"
          value={value.max_up / 100}
          onChange={(v) => onChange({ max_up: Math.round(v * 100) })}
        />
        <SliderRow
          label="Max up — fast strokes"
          value={value.max_up_fast / 100}
          onChange={(v) => onChange({ max_up_fast: Math.round(v * 100) })}
        />
        <SliderRow
          label="Max down — fast strokes"
          value={value.max_down_fast / 100}
          onChange={(v) => onChange({ max_down_fast: Math.round(v * 100) })}
        />
        <SliderRow
          label="Max down — slow strokes (base)"
          value={value.max_down / 100}
          onChange={(v) => onChange({ max_down: Math.round(v * 100) })}
        />
        <p className="mt-1 text-xs text-slate-500">
          Slow: {value.max_down}→{value.max_up}. Fast: {value.max_down_fast}→{value.max_up_fast}.
          Set the fast values equal to their slow neighbors to disable per-speed variation on that end.
        </p>
      </div>

      <div className="mt-5 pt-3 border-t border-slate-800">
        <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">
          Musical shape
        </p>
        <SliderRow
          label="Section variety"
          value={value.variety_amount}
          onChange={(v) => onChange({ variety_amount: v })}
        />
        <p className="mt-1 text-xs text-slate-500">
          Rhythmic runs share one peak height for consistency. At
          higher variety, each section picks a different sub-range so
          it doesn't sound flat. 0 = every section identical, 1 =
          maximum swing between sections.
        </p>
        <label className="mt-3 flex items-center gap-3 text-sm text-slate-300 touch-manipulation">
          <input
            type="checkbox"
            checked={value.idle_enabled}
            onChange={(e) => onChange({ idle_enabled: e.target.checked })}
            className="w-5 h-5 accent-indigo-500"
          />
          <span>
            Idle animation in silent gaps
            <span className="text-slate-500 ml-2">
              (slow oscillation before first beat, between sections, after last beat)
            </span>
          </span>
        </label>
      </div>
    </>
  )
}

function SliderRow({
  label,
  value,
  onChange,
}: {
  label: string
  value: number
  onChange: (v: number) => void
}) {
  return (
    <div className="mt-3">
      <div className="flex justify-between text-xs text-slate-400 mb-1">
        <span>{label}</span>
        <span className="font-mono">{Math.round(value * 100)}%</span>
      </div>
      <input
        type="range"
        min={0}
        max={1000}
        value={Math.round(value * 1000)}
        onChange={(e) => onChange(parseInt(e.target.value, 10) / 1000)}
        className="w-full touch-none"
      />
    </div>
  )
}

// Constraint helper — call from the parent's setter to keep
// max_down ≤ max_down_fast ≤ max_up_fast ≤ max_up coherent no matter
// which slider the user just tugged.
export function clampShape<S extends Shape>(next: S): S {
  const max_up = Math.max(0, Math.min(100, next.max_up))
  const max_down = Math.max(0, Math.min(max_up, next.max_down))
  const max_up_fast = Math.max(max_down, Math.min(max_up, next.max_up_fast))
  const max_down_fast = Math.max(max_down, Math.min(max_up_fast, next.max_down_fast))
  return { ...next, max_up, max_up_fast, max_down_fast, max_down }
}
