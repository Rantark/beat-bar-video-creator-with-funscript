import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { BeatShapeControls, clampShape } from '../components/BeatShapeControls'
import { LineDrawer } from '../components/LineDrawer'
import { MarkerDrawer } from '../components/MarkerDrawer'
import { BeatPatternEditor } from '../components/BeatPatternEditor'
import { PresetControls } from '../components/PresetControls'
import { SpriteScrubber } from '../components/SpriteScrubber'
import { SpriteUpload } from '../components/SpriteUpload'
import { ZoneDrawer } from '../components/ZoneDrawer'
import type { Audio, Line, Marker, VideoMeta, Zone } from '../types'

// Fields that get saved into a preset — only the *tuning* knobs, never
// spatial placement (marker x/y/radius, line x/y/length/orientation) so a
// preset applies cleanly to any video.
const MARKER_PRESET_KEYS = [
  'max_up', 'max_up_fast', 'max_down_fast', 'max_down',
  'variety_amount', 'idle_enabled', 'sensitivity', 'motion_smoothing',
] as const
const LINE_PRESET_KEYS = [
  'max_up', 'max_up_fast', 'max_down_fast', 'max_down',
  'variety_amount', 'idle_enabled', 'motion_smoothing',
] as const

function pickKeys<T extends Record<string, unknown>>(
  src: T, keys: readonly string[],
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const k of keys) if (k in src) out[k] = (src as Record<string, unknown>)[k]
  return out
}

type Mode = 'zone' | 'line' | 'marker' | 'audio'

export default function FramePickerPage() {
  const { videoId } = useParams()
  const navigate = useNavigate()
  const videoRef = useRef<HTMLVideoElement>(null)

  const [video, setVideo] = useState<VideoMeta | null>(null)
  const [mode, setMode] = useState<Mode>('zone')
  const [zone, setZone] = useState<Zone | null>(null)
  const [invert, setInvert] = useState(false)
  const [line, setLine] = useState<Line>({
    orientation: 'horizontal',
    x: 0.5,
    y: 0.5,
    length: 1.0,
    max_up: 100,
    max_up_fast: 100,
    max_down_fast: 0,
    max_down: 0,
    variety_amount: 0,
    idle_enabled: true,
    motion_smoothing: 2,
  })
  const [marker, setMarker] = useState<Marker>({
    x: 0.5,
    y: 0.5,
    radius: 0.02,
    max_up: 100,
    max_up_fast: 100,
    max_down_fast: 0,
    max_down: 0,
    variety_amount: 0,
    idle_enabled: true,
    sensitivity: 0.5,
    motion_smoothing: 2,
    template: null,
  })
  const [audio, setAudio] = useState<Audio>({
    sensitivity: 0.5,
    min_gap_ms: 120,
    low_hz: 60,
    high_hz: 8000,
    use_neural: false,
    neural_tightness: 100,
    regularize: true,
    section_min_ms: 10000,
    section_target_ms: 20000,
    section_max_ms: 30000,
    section_fluctuation: 0,
    pattern_variety: 0,
    patterns: [],
    lookahead_ms: 1500,
    bar_image: null,
    hit_image: null,
    beat_image: null,
    max_up: 100,
    max_up_fast: 100,
    max_down_fast: 0,
    max_down: 0,
    variety_amount: 0,
    idle_enabled: true,
    motion_smoothing: 2,
  })
  function updateAudio(patch: Partial<Audio>) {
    setAudio((prev) => clampShape({ ...prev, ...patch }))
  }

  // Enforce max_down ≤ max_down_fast ≤ max_up_fast ≤ max_up whenever any
  // of them changes. Keeps sliders coherent no matter what order the
  // user tugs. Shared with line mode via clampShape helper.
  function updateMarker(patch: Partial<Marker>) {
    setMarker((prev) => clampShape({ ...prev, ...patch }))
  }
  function updateLine(patch: Partial<Line>) {
    setLine((prev) => clampShape({ ...prev, ...patch }))
  }
  // Default off in general, but auto-on in audio mode where the
  // scrolling beat bar overlay is the whole point of the mode. Users
  // can still opt out to skip the render.
  const [debug, setDebug] = useState(false)
  useEffect(() => {
    if (mode === 'audio') setDebug(true)
  }, [mode])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Poll until the sprite is generated, then stop. Interval kept short
  // (400ms) because sprite gen on a short clip is often sub-second.
  useEffect(() => {
    if (!videoId) return
    let cancelled = false
    let timer: number | undefined
    async function tick() {
      try {
        const v = await api.getVideo(videoId!)
        if (cancelled) return
        setVideo(v)
        if (!v.sprite_ready) timer = window.setTimeout(tick, 400)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      }
    }
    tick()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [videoId])

  function seek(ms: number) {
    if (videoRef.current) videoRef.current.currentTime = ms / 1000
  }

  async function submit() {
    if (!video) return
    if (mode === 'zone' && (!zone || zone.w < 0.02 || zone.h < 0.02)) {
      setError('Draw a zone on the video first (touch and drag).')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const shape =
        mode === 'zone' ? { zone, invert } :
        mode === 'line' ? { line } :
        mode === 'marker' ? { marker } :
        { audio }
      const params = { ...shape, debug }
      await api.createJob({ video_id: video.id, mode, params })
      navigate('/jobs')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  if (error && !video) return <p className="p-4 text-red-400">{error}</p>
  if (!video) return <p className="p-4 text-slate-400">Loading video…</p>
  if (video.download_status === 'failed') {
    return (
      <div className="p-4 max-w-md mx-auto">
        <p className="text-red-400 font-medium mb-2">URL download failed.</p>
        <pre className="text-xs text-red-300 whitespace-pre-wrap break-words bg-slate-900 p-3 rounded border border-red-900/50 max-h-64 overflow-auto">
          {video.download_error || 'unknown error'}
        </pre>
      </div>
    )
  }
  if (video.download_status === 'queued' || video.download_status === 'downloading') {
    const pct = Math.round((video.download_progress || 0) * 100)
    return (
      <div className="p-4 max-w-md mx-auto">
        <p className="text-amber-400 mb-2">
          {video.download_status === 'queued'
            ? 'Queued — waiting for prior download to finish…'
            : `Downloading… ${pct}%`}
        </p>
        <p className="text-xs text-slate-500 mb-3 break-all font-mono">
          {video.source_url}
        </p>
        <div className="h-2 bg-slate-800 rounded">
          <div
            className="h-2 bg-indigo-500 rounded transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    )
  }
  if (!video.sprite_ready)
    return <p className="p-4 text-amber-400">Generating thumbnails for {video.filename}…</p>

  return (
    <div className="p-4 max-w-2xl md:max-w-4xl mx-auto">
      <p className="text-sm text-slate-400 mb-2 truncate">{video.filename}</p>
      <div
        className="relative bg-black mx-auto"
        style={{
          aspectRatio: `${video.width} / ${video.height}`,
          // Cap width by the height that would fit at 70% of viewport.
          // A tall (portrait) video on desktop would otherwise dominate
          // the page and push controls below the fold.
          maxWidth: `calc(70dvh * ${video.width / video.height})`,
        }}
      >
        <video
          ref={videoRef}
          src={api.streamUrl(video.id)}
          className="w-full h-full"
          // Firefox refuses to render a video frame to canvas until at
          // least one has been decoded — which won't happen at all with
          // preload="metadata". "auto" fetches enough data that we can
          // paint the first frame, which is what the loupe needs.
          preload="auto"
          playsInline
          muted
        />
        {mode === 'zone' && <ZoneDrawer zone={zone} onChange={setZone} />}
        {mode === 'line' && <LineDrawer line={line} />}
        {mode === 'marker' && (
          <MarkerDrawer
            marker={marker}
            onChange={setMarker}
            videoRef={videoRef}
            videoDims={{ width: video.width, height: video.height }}
          />
        )}
      </div>

      <SpriteScrubber video={video} onSeek={seek} />

      <div className="flex gap-2 mt-4">
        <ModeButton active={mode === 'zone'} onClick={() => setMode('zone')}>
          Zone
        </ModeButton>
        <ModeButton active={mode === 'line'} onClick={() => setMode('line')}>
          Line
        </ModeButton>
        <ModeButton active={mode === 'marker'} onClick={() => setMode('marker')}>
          Marker
        </ModeButton>
        <ModeButton active={mode === 'audio'} onClick={() => setMode('audio')}>
          Audio
        </ModeButton>
      </div>

      {mode === 'zone' && (
        <>
          <div className="mt-3 text-sm text-slate-400">
            {zone && zone.w > 0.01 && zone.h > 0.01 ? (
              <>
                Zone: {(zone.x * 100).toFixed(0)},{(zone.y * 100).toFixed(0)} —
                {' '}
                {(zone.w * 100).toFixed(0)}×{(zone.h * 100).toFixed(0)}%
                <button
                  onClick={() => setZone(null)}
                  className="ml-3 underline text-slate-300"
                >
                  clear
                </button>
              </>
            ) : (
              <>Touch and drag on the video to draw a zone.</>
            )}
          </div>
          <label className="mt-3 flex items-center gap-3 text-sm text-slate-300 touch-manipulation">
            <input
              type="checkbox"
              checked={invert}
              onChange={(e) => setInvert(e.target.checked)}
              className="w-5 h-5 accent-indigo-500"
            />
            <span>
              Invert direction
              <span className="text-slate-500 ml-2">
                (flip if the output feels backwards)
              </span>
            </span>
          </label>
        </>
      )}

      {mode === 'line' && (
        <div className="mt-3">
          <div className="flex gap-2">
            <ModeButton
              active={line.orientation === 'horizontal'}
              onClick={() => updateLine({ orientation: 'horizontal' })}
              small
            >
              Horizontal
            </ModeButton>
            <ModeButton
              active={line.orientation === 'vertical'}
              onClick={() => updateLine({ orientation: 'vertical' })}
              small
            >
              Vertical
            </ModeButton>
          </div>
          <SliderRow
            label="Center X"
            value={line.x}
            onChange={(v) => updateLine({ x: v })}
          />
          <SliderRow
            label="Center Y"
            value={line.y}
            onChange={(v) => updateLine({ y: v })}
          />
          <SliderRow
            label="Length"
            value={line.length}
            onChange={(v) => updateLine({ length: v })}
          />
          <p className="mt-2 text-xs text-slate-500">
            Only motion inside the highlighted strip counts as a crossing.
          </p>

          <PresetControls
            mode="line"
            currentParams={pickKeys(line, LINE_PRESET_KEYS)}
            onLoad={(p) => updateLine(p as Partial<Line>)}
          />

          <BeatShapeControls
            value={line}
            onChange={(patch) => updateLine(patch as Partial<Line>)}
            showSensitivity={false}
          />
        </div>
      )}

      {mode === 'marker' && (
        <div className="mt-3">
          <p className="text-sm text-slate-400">
            Touch on the video where beats land. Hold to see the zoom loupe.
          </p>
          <SliderRow
            label="Marker size"
            value={(marker.radius - 0.005) / (0.06 - 0.005)}
            onChange={(v) =>
              setMarker({ ...marker, radius: 0.005 + v * (0.06 - 0.005) })
            }
          />

          <PresetControls
            mode="marker"
            currentParams={pickKeys(marker, MARKER_PRESET_KEYS)}
            onLoad={(p) => updateMarker(p as Partial<Marker>)}
          />

          <TemplatePanel
            marker={marker}
            onChange={(t) => updateMarker({ template: t })}
            videoRef={videoRef}
          />

          <BeatShapeControls
            value={marker}
            onChange={(patch) => updateMarker(patch as Partial<Marker>)}
            showSensitivity
          />
        </div>
      )}

      {mode === 'audio' && (
        <div className="mt-3">
          <p className="text-sm text-slate-400">
            Detects beats from the source video's audio track — no on-screen
            beat bar needed. The debug render draws a synthetic beat bar
            with the novelty curve + detected onsets so you can eyeball
            the result. Best for content where music carries the rhythm.
          </p>
          <div className="mt-3">
            <div className="flex justify-between text-xs text-slate-400 mb-1">
              <span>Sensitivity</span>
              <span className="font-mono">{Math.round(audio.sensitivity * 100)}%</span>
            </div>
            <input
              type="range" min={0} max={1000}
              value={Math.round(audio.sensitivity * 1000)}
              onChange={(e) => updateAudio({ sensitivity: parseInt(e.target.value, 10) / 1000 })}
              className="w-full touch-none"
            />
            <p className="text-xs text-slate-500 mt-1">
              0 = only strong percussive hits · 1 = catches faint accents (more noise)
            </p>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <label className="text-xs text-slate-400">
              <span className="block mb-1">Min gap (ms)</span>
              <input
                type="number" min={20} max={2000}
                value={audio.min_gap_ms}
                onChange={(e) => updateAudio({ min_gap_ms: parseInt(e.target.value, 10) || 120 })}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 font-mono"
              />
            </label>
            <label className="text-xs text-slate-400">
              <span className="block mb-1">Low Hz</span>
              <input
                type="number" min={20} max={2000}
                value={audio.low_hz}
                onChange={(e) => updateAudio({ low_hz: parseInt(e.target.value, 10) || 60 })}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 font-mono"
              />
            </label>
            <label className="text-xs text-slate-400">
              <span className="block mb-1">High Hz</span>
              <input
                type="number" min={500} max={20000}
                value={audio.high_hz}
                onChange={(e) => updateAudio({ high_hz: parseInt(e.target.value, 10) || 8000 })}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 font-mono"
              />
            </label>
          </div>
          <p className="text-xs text-slate-500 mt-2">
            Narrow the frequency band to isolate what carries the rhythm.
            Kicks live below 200 Hz; snares/hats 200–8000. Voice-heavy content:
            try 100–500 Hz.
          </p>

          <div className="mt-5 pt-3 border-t border-slate-800">
            <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">
              Detection engine
            </p>
            <label className="flex items-center gap-3 text-sm text-slate-300 touch-manipulation">
              <input
                type="checkbox"
                checked={audio.use_neural}
                onChange={(e) => updateAudio({ use_neural: e.target.checked })}
                className="w-5 h-5 accent-indigo-500"
              />
              <span>
                Neural beat tracker
                <span className="text-slate-500 ml-2">
                  (learned tempo prior + dynamic-programming beat picker,
                  more accurate on real music — slower, requires the
                  [neural] backend install)
                </span>
              </span>
            </label>
            <div className={`mt-3 ${audio.use_neural ? '' : 'opacity-40 pointer-events-none'}`}>
              <div className="flex justify-between text-xs text-slate-400 mb-1">
                <span>Tempo tightness</span>
                <span className="font-mono">{audio.neural_tightness}</span>
              </div>
              <input
                type="range" min={20} max={400} step={10}
                value={audio.neural_tightness}
                onChange={(e) => updateAudio({
                  neural_tightness: parseInt(e.target.value, 10) || 100,
                })}
                className="w-full touch-none"
              />
              <p className="text-xs text-slate-500 mt-1">
                Higher = picker sticks harder to the estimated tempo
                (good for steady electronic tracks). Lower = more
                flexible to tempo drift (good for live/acoustic music).
                Default 100.
              </p>
            </div>
            <p className="mt-3 text-xs text-slate-500">
              With this off, audio-mode uses the raw spectral-flux
              onset detector (faster, always available, less musically
              accurate). The sensitivity / min-gap / frequency-band
              knobs above apply to the spectral-flux path only.
            </p>
          </div>

          <div className="mt-5 pt-3 border-t border-slate-800">
            <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">
              Rhythm consistency
            </p>
            <label className="flex items-center gap-3 text-sm text-slate-300 touch-manipulation">
              <input
                type="checkbox"
                checked={audio.regularize}
                onChange={(e) => updateAudio({ regularize: e.target.checked })}
                className="w-5 h-5 accent-indigo-500"
              />
              <span>
                Lock a steady tempo per section
                <span className="text-slate-500 ml-2">
                  (turns raw onset detection into a rhythm-game chart —
                  consistent inside each section, tempo shifts at boundaries)
                </span>
              </span>
            </label>
            <div className={`mt-3 ${audio.regularize ? '' : 'opacity-40 pointer-events-none'}`}>
              <div className="grid grid-cols-3 gap-3">
                <SectionSecInput
                  label="Min"
                  value={audio.section_min_ms}
                  onChange={(v) => updateAudio(clampSections({
                    ...audio, section_min_ms: v,
                  }))}
                />
                <SectionSecInput
                  label="Target"
                  value={audio.section_target_ms}
                  onChange={(v) => updateAudio(clampSections({
                    ...audio, section_target_ms: v,
                  }))}
                />
                <SectionSecInput
                  label="Max"
                  value={audio.section_max_ms}
                  onChange={(v) => updateAudio(clampSections({
                    ...audio, section_max_ms: v,
                  }))}
                />
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Section length in seconds, quantized to multiples of 5.
                Min ≤ target ≤ max is enforced automatically.
              </p>
              <div className="mt-3">
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>Fluctuation</span>
                  <span className="font-mono">
                    {Math.round(audio.section_fluctuation * 100)}%
                  </span>
                </div>
                <input
                  type="range" min={0} max={1000}
                  value={Math.round(audio.section_fluctuation * 1000)}
                  onChange={(e) => updateAudio({
                    section_fluctuation: parseInt(e.target.value, 10) / 1000,
                  })}
                  className="w-full touch-none"
                />
                <p className="text-xs text-slate-500 mt-1">
                  0% = every section is exactly the target length.
                  100% = section length ranges freely between min and max
                  (still snapped to 5-second multiples). Section layout is
                  seeded from the detected onsets, so re-runs on the same
                  audio give the same layout.
                </p>
              </div>
              <div className="mt-4">
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>Beat-pattern variety</span>
                  <span className="font-mono">
                    {Math.round(audio.pattern_variety * 100)}%
                  </span>
                </div>
                <input
                  type="range" min={0} max={1000}
                  value={Math.round(audio.pattern_variety * 1000)}
                  onChange={(e) => updateAudio({
                    pattern_variety: parseInt(e.target.value, 10) / 1000,
                  })}
                  className="w-full touch-none"
                />
                <p className="text-xs text-slate-500 mt-1">
                  Chance that a section switches to half-time (2× the
                  detected period) or double-time (½× the detected
                  period). 0% = every section uses the audio's detected
                  tempo. 50% = about half of sections shift subdivision.
                  Use this when the music holds one steady tempo but you
                  still want visibly different rhythms per section.
                </p>
              </div>
              <BeatPatternEditor
                patterns={audio.patterns}
                onChange={(patterns) => updateAudio({ patterns })}
              />
            </div>
          </div>

          <div className="mt-5 pt-3 border-t border-slate-800">
            <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">
              Rhythm-game overlay (debug render only)
            </p>
            <p className="text-xs text-slate-500 mb-3">
              When Render debug video is on, the audio track's beats scroll
              across a bar at the bottom of the frame and cross a fixed hit
              marker at exactly their onset time. Upload custom sprites to
              match a specific game's look, or leave them empty for the
              plain defaults.
            </p>
            <div className="flex flex-col gap-3">
              <SpriteUpload
                label="Bar background"
                hint="Fills the strip. Any image, opaque. PNG/JPG."
                value={audio.bar_image}
                onChange={(v) => updateAudio({ bar_image: v })}
              />
              <SpriteUpload
                label="Hit marker"
                hint="Fixed at ~20% from left. Transparent PNG recommended."
                value={audio.hit_image}
                onChange={(v) => updateAudio({ hit_image: v })}
              />
              <SpriteUpload
                label="Beat sprite"
                hint="Drawn for each scrolling beat. Transparent PNG recommended."
                value={audio.beat_image}
                onChange={(v) => updateAudio({ beat_image: v })}
              />
            </div>
            <div className="mt-3">
              <div className="flex justify-between text-xs text-slate-400 mb-1">
                <span>Lookahead</span>
                <span className="font-mono">{audio.lookahead_ms} ms</span>
              </div>
              <input
                type="range" min={400} max={4000} step={100}
                value={audio.lookahead_ms}
                onChange={(e) => updateAudio({
                  lookahead_ms: parseInt(e.target.value, 10) || 1500,
                })}
                className="w-full touch-none"
              />
              <p className="text-xs text-slate-500 mt-1">
                How long each beat is visible before it hits the marker.
                Shorter = faster scroll, more space between beats.
              </p>
            </div>
          </div>

          <BeatShapeControls
            value={audio}
            onChange={(patch) => updateAudio(patch as Partial<Audio>)}
            showSensitivity={false}
          />
        </div>
      )}

      <label className={`mt-6 flex items-center gap-3 text-sm touch-manipulation ${
        mode === 'audio'
          ? 'p-3 rounded-lg bg-indigo-950/40 border border-indigo-800/50 text-indigo-100'
          : 'text-slate-300'
      }`}>
        <input
          type="checkbox"
          checked={debug}
          onChange={(e) => setDebug(e.target.checked)}
          className="w-5 h-5 accent-indigo-500"
        />
        <span>
          {mode === 'audio' ? (
            <>
              <span className="font-medium">Render beat-bar video</span>
              <span className="text-indigo-300 ml-2">
                (the scrolling rhythm-game overlay you configured above —
                the whole point of Audio mode. Uncheck only if you just
                want the raw funscript.)
              </span>
            </>
          ) : (
            <>
              Render debug video
              <span className="text-slate-500 ml-2">
                (annotated MP4 with audio — slower, but shows what the algorithm saw)
              </span>
            </>
          )}
        </span>
      </label>

      <button
        onClick={submit}
        disabled={submitting}
        className="w-full mt-4 py-4 rounded-lg bg-emerald-600 disabled:opacity-40 text-lg touch-manipulation"
      >
        {submitting ? 'Submitting…' : 'Generate funscript'}
      </button>
      {error && <p className="mt-3 text-sm text-red-400 break-words">{error}</p>}
    </div>
  )
}

/** Seconds input for a section length. Snaps to 5-second steps and
 *  keeps its value in ms so the parent state stays in ms throughout. */
function SectionSecInput({
  label,
  value,
  onChange,
}: {
  label: string
  value: number
  onChange: (ms: number) => void
}) {
  const seconds = Math.round(value / 1000)
  return (
    <label className="text-xs text-slate-400">
      <span className="block mb-1">{label} (s)</span>
      <input
        type="number" min={5} step={5}
        value={seconds}
        onChange={(e) => {
          const s = Math.max(5, Math.round((parseInt(e.target.value, 10) || 5) / 5) * 5)
          onChange(s * 1000)
        }}
        className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 font-mono"
      />
    </label>
  )
}

/** Enforce section_min_ms ≤ section_target_ms ≤ section_max_ms whenever
 *  any of the three changes. All values already come in as 5s multiples. */
function clampSections(a: Audio): Partial<Audio> {
  const min = Math.max(5000, a.section_min_ms)
  const max = Math.max(min, a.section_max_ms)
  const target = Math.max(min, Math.min(max, a.section_target_ms))
  return {
    section_min_ms: min,
    section_target_ms: target,
    section_max_ms: max,
  }
}

function ModeButton({
  active,
  onClick,
  children,
  small,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
  small?: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 ${small ? 'py-2' : 'py-3'} rounded touch-manipulation ${
        active ? 'bg-indigo-600' : 'bg-slate-700'
      }`}
    >
      {children}
    </button>
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

/**
 * Optional template capture — snapshots the current video frame around
 * the marker circle and hands it to the backend as a base64 data URL.
 * When present, the backend runs cv2.matchTemplate at the hit-point
 * ROI each frame and adds the score as an extra signal component. Way
 * more discriminative than color contrast alone for consistent visual
 * beat markers (rings, symbols, icons).
 */
function TemplatePanel({
  marker,
  onChange,
  videoRef,
}: {
  marker: Marker
  onChange: (data: string | null) => void
  videoRef: React.RefObject<HTMLVideoElement | null>
}) {
  function capture() {
    const video = videoRef.current
    if (!video || video.videoWidth === 0) return
    // Grab a square region centered on the marker circle, sized to
    // ~2× the marker radius so the template captures the ring plus a
    // small bit of background — cv2.matchTemplate then finds the same
    // pattern in each frame's ROI regardless of exact placement.
    const vw = video.videoWidth
    const vh = video.videoHeight
    const cx = marker.x * vw
    const cy = marker.y * vh
    const r = marker.radius * Math.min(vw, vh)
    const size = Math.max(20, Math.round(r * 2))
    const c = document.createElement('canvas')
    c.width = size
    c.height = size
    const ctx = c.getContext('2d')!
    ctx.fillStyle = '#000'
    ctx.fillRect(0, 0, size, size)
    ctx.drawImage(
      video,
      cx - size / 2, cy - size / 2, size, size,  // source
      0, 0, size, size,                          // dest
    )
    try {
      onChange(c.toDataURL('image/png'))
    } catch {
      // Older Firefox may throw if the video frame isn't decoded yet —
      // the loupe-fix's preload="auto" + micro-seek should have already
      // triggered a decode; if not, ask the user to scrub first.
      onChange(null)
    }
  }

  return (
    <div className="mt-4 pt-3 border-t border-slate-800">
      <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">
        Template matching (optional)
      </p>
      <p className="text-xs text-slate-500 mb-2">
        Advance the video to a frame where a beat marker is visible, then
        capture. The backend will run visual template matching alongside
        the color signals — much more accurate for consistent markers.
      </p>
      <div className="flex items-center gap-3">
        {marker.template ? (
          <>
            <img
              src={marker.template}
              alt="captured template"
              className="w-20 h-20 object-cover border border-slate-700 rounded bg-black"
            />
            <button
              onClick={() => onChange(null)}
              className="px-3 py-2 rounded text-sm bg-slate-700 hover:bg-slate-600"
            >
              Remove template
            </button>
            <button
              onClick={capture}
              className="px-3 py-2 rounded text-sm bg-slate-700 hover:bg-slate-600"
            >
              Re-capture
            </button>
          </>
        ) : (
          <button
            onClick={capture}
            className="px-3 py-2 rounded text-sm bg-indigo-600 hover:bg-indigo-500"
          >
            Capture template from current frame
          </button>
        )}
      </div>
    </div>
  )
}
