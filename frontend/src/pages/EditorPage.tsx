import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { StrokerVisualizer } from '../components/StrokerVisualizer'
import { TimelineGraph, type EditAction } from '../components/TimelineGraph'
import type { Action, Job, JobMeta, VideoMeta } from '../types'
import { fmtMs } from '../util'

const ZOOM_LEVELS = [10, 20, 40, 80, 160, 320]
const DEFAULT_ZOOM_IDX = 2

// Stable IDs assigned on load — survive re-sorts after drags so the
// user's selection Set doesn't get invalidated by index shifts.
let idCounter = 0
const nextId = () => `a${++idCounter}`

export default function EditorPage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const videoRef = useRef<HTMLVideoElement>(null)

  const [job, setJob] = useState<Job | null>(null)
  const [video, setVideo] = useState<VideoMeta | null>(null)
  const [meta, setMeta] = useState<JobMeta | null>(null)
  const [actions, setActions] = useState<EditAction[]>([])
  const [selection, setSelection] = useState<Set<string>>(new Set())
  const [selectMode, setSelectMode] = useState(false)
  const [cursorMs, setCursorMs] = useState(0)
  const [zoomIdx, setZoomIdx] = useState(DEFAULT_ZOOM_IDX)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rerendering, setRerendering] = useState(false)
  const [rerenderProgress, setRerenderProgress] = useState(0)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [muted, setMuted] = useState(false)
  // A/B loop — when both A and B are set and loopEnabled is true, the
  // video jumps back to A whenever playback passes B. Iterative tuning
  // aid: set the loop around a bad section, tweak, hear the change.
  const [loopA, setLoopA] = useState<number | null>(null)
  const [loopB, setLoopB] = useState<number | null>(null)
  const [loopEnabled, setLoopEnabled] = useState(false)
  // Fill-range pattern params. Kept as component state so tuning
  // survives Apply/undo cycles while iterating on a bad section.
  const [fillPattern, setFillPattern] = useState<'flat' | 'beat' | 'ramp'>('beat')
  const [fillHoldPos, setFillHoldPos] = useState(0)
  const [fillBeatBpm, setFillBeatBpm] = useState(60)
  const [fillBeatMin, setFillBeatMin] = useState(10)
  const [fillBeatMax, setFillBeatMax] = useState(90)
  const [fillRampFrom, setFillRampFrom] = useState(0)
  const [fillRampTo, setFillRampTo] = useState(100)
  const historyRef = useRef<EditAction[][]>([])
  // Captured on pointer-down; used to compute group deltas without
  // re-referencing possibly-mutated action objects during the drag.
  const dragOriginsRef = useRef<Map<string, EditAction> | null>(null)

  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    async function load() {
      try {
        const [j, fs, m] = await Promise.all([
          api.getJob(jobId!),
          api.getFunscript(jobId!),
          api.getJobMeta(jobId!),
        ])
        if (cancelled) return
        setJob(j)
        setActions(fs.actions.map((a) => ({ ...a, id: nextId() })))
        setMeta(m)
        const v = await api.getVideo(j.video_id)
        if (cancelled) return
        setVideo(v)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [jobId])

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const tick = () => {
      setCursorMs(Math.round(v.currentTime * 1000))
      // A/B loop enforcement — snap back to A the instant we cross B.
      // Guarded to only fire during playback so a manual scrub past B
      // doesn't feel like the video is fighting the user.
      if (
        loopEnabled && !v.paused
        && loopA !== null && loopB !== null && loopB > loopA
        && v.currentTime * 1000 >= loopB
      ) {
        v.currentTime = loopA / 1000
      }
    }
    v.addEventListener('timeupdate', tick)
    v.addEventListener('seeked', tick)
    return () => {
      v.removeEventListener('timeupdate', tick)
      v.removeEventListener('seeked', tick)
    }
  }, [video, loopA, loopB, loopEnabled])

  // Keyboard shortcuts. Use a live ref for the handler so the effect
  // only wires the listener once, but every keystroke sees the current
  // state and closures.
  const keyHandlerRef = useRef<(e: KeyboardEvent) => void>(() => {})
  useEffect(() => {
    const listener = (e: KeyboardEvent) => keyHandlerRef.current(e)
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])

  function pushHistory() {
    historyRef.current.push(actions.map((a) => ({ ...a })))
    if (historyRef.current.length > 200) historyRef.current.shift()
  }

  function onPointDown(id: string) {
    let newSel: Set<string>
    if (selectMode) {
      newSel = new Set(selection)
      if (newSel.has(id)) newSel.delete(id)
      else newSel.add(id)
    } else {
      newSel = new Set([id])
    }
    setSelection(newSel)
    // Capture origins for the whole (post-toggle) selection so a group
    // drag can proceed if the user starts moving.
    const origins = new Map<string, EditAction>()
    newSel.forEach((sid) => {
      const a = actions.find((a) => a.id === sid)
      if (a) origins.set(sid, { ...a })
    })
    // Also always include the point being dragged even if select-mode
    // deselected it — releasing a drag with no target is confusing.
    if (!origins.has(id)) {
      const a = actions.find((a) => a.id === id)
      if (a) origins.set(id, { ...a })
    }
    dragOriginsRef.current = origins
    pushHistory()
  }

  function onDragDelta(dtMs: number, dPos: number) {
    const origins = dragOriginsRef.current
    if (!origins) return
    setActions((prev) =>
      prev.map((a) => {
        const origin = origins.get(a.id)
        if (!origin) return a
        return {
          ...a,
          at: Math.max(0, origin.at + dtMs),
          pos: Math.max(0, Math.min(100, origin.pos + dPos)),
        }
      }),
    )
    setDirty(true)
  }

  function onDragEnd() {
    dragOriginsRef.current = null
    // Sort by `at` — safe now because we key by id, not index.
    setActions((prev) => [...prev].sort((a, b) => a.at - b.at))
  }

  function onEmptyTap(at: number, pos: number) {
    if (videoRef.current) videoRef.current.currentTime = at / 1000
    if (selectMode) {
      setSelection(new Set())
      return
    }
    // Edit mode: also add a point at that (time, pos).
    pushHistory()
    const na: EditAction = { id: nextId(), at, pos }
    setActions((prev) => [...prev, na].sort((a, b) => a.at - b.at))
    setSelection(new Set([na.id]))
    setDirty(true)
  }

  function onRubberBand(b: { at1: number; at2: number; pos1: number; pos2: number }) {
    const inside = actions.filter(
      (a) => a.at >= b.at1 && a.at <= b.at2 && a.pos >= b.pos1 && a.pos <= b.pos2,
    )
    setSelection((prev) => {
      const next = new Set(prev)
      inside.forEach((a) => next.add(a.id))
      return next
    })
  }

  function nudge(dAt: number, dPos: number) {
    if (selection.size === 0) return
    pushHistory()
    setActions((prev) =>
      prev.map((a) =>
        selection.has(a.id)
          ? {
              ...a,
              at: Math.max(0, a.at + dAt),
              pos: Math.max(0, Math.min(100, a.pos + dPos)),
            }
          : a,
      ),
    )
    setDirty(true)
  }

  function deleteSelected() {
    if (selection.size === 0) return
    pushHistory()
    setActions((prev) => prev.filter((a) => !selection.has(a.id)))
    setSelection(new Set())
    setDirty(true)
  }

  function setSelectedPos(newPos: number) {
    if (selection.size !== 1) return
    pushHistory()
    const clamped = Math.max(0, Math.min(100, Math.round(newPos)))
    setActions((prev) =>
      prev.map((a) => (selection.has(a.id) ? { ...a, pos: clamped } : a)),
    )
    setDirty(true)
  }

  function setSelectedAt(newAt: number) {
    if (selection.size !== 1) return
    pushHistory()
    const clamped = Math.max(0, Math.round(newAt))
    setActions((prev) =>
      prev
        .map((a) => (selection.has(a.id) ? { ...a, at: clamped } : a))
        .sort((a, b) => a.at - b.at),
    )
    setDirty(true)
  }

  function selectPeaks() {
    const ids = actions.filter((a) => a.pos >= 80).map((a) => a.id)
    setSelection(new Set(ids))
  }
  function selectTroughs() {
    const ids = actions.filter((a) => a.pos <= 20).map((a) => a.id)
    setSelection(new Set(ids))
  }
  function selectAll() {
    setSelection(new Set(actions.map((a) => a.id)))
  }
  function deselectAll() {
    setSelection(new Set())
  }

  function undo() {
    const prev = historyRef.current.pop()
    if (prev) {
      setActions(prev)
      setSelection(new Set())
      setDirty(true)
    }
  }

  async function rerenderDebug() {
    if (!jobId || !job) return
    if (dirty) {
      if (!confirm('You have unsaved edits — save them first? Cancel = save, OK = rebuild against the last saved version.')) {
        await save()
        // fall through to re-render only after save resolves
      }
    }
    setRerendering(true)
    setRerenderProgress(0)
    setError(null)
    try {
      await api.rerenderDebug(jobId)
      // Poll the job's progress until it comes back to "done".
      const pollUntilDone = async () => {
        for (let i = 0; i < 600; i++) {
          const j = await api.getJob(jobId)
          setRerenderProgress(j.progress)
          if (j.status === 'done') {
            setJob(j)
            return
          }
          if (j.status === 'failed') {
            throw new Error(j.error || 'rerender failed')
          }
          await new Promise((r) => setTimeout(r, 500))
        }
        throw new Error('rerender timed out')
      }
      await pollUntilDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRerendering(false)
      // Force <video> to reload the new file (same URL — bust cache).
      const v = videoRef.current
      if (v) {
        const t = v.currentTime
        v.src = `${api.debugUrl(jobId!)}?t=${Date.now()}`
        v.load()
        v.currentTime = t
      }
    }
  }

  async function save() {
    if (!jobId) return
    setSaving(true)
    setError(null)
    try {
      const bare: Action[] = actions.map(({ at, pos }) => ({ at, pos }))
      const res = await api.saveFunscript(jobId, bare)
      setDirty(false)
      if (job) setJob({ ...job, has_original: res.has_original })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  function applyPlaybackRate(r: number) {
    setPlaybackRate(r)
    if (videoRef.current) videoRef.current.playbackRate = r
  }
  function togglePlay() {
    const v = videoRef.current
    if (!v) return
    if (v.paused) v.play()
    else v.pause()
  }
  function frameStep(dFrames: number) {
    const v = videoRef.current
    if (!v || !video) return
    v.pause()
    const fps = video.fps || 30
    v.currentTime = Math.max(
      0,
      Math.min(v.duration || Infinity, v.currentTime + dFrames / fps),
    )
  }
  function seekBy(dMs: number) {
    const v = videoRef.current
    if (!v) return
    v.currentTime = Math.max(0, Math.min(v.duration || Infinity, v.currentTime + dMs / 1000))
  }
  function toggleMute() {
    setMuted((m) => !m)
  }

  function setLoopFromCursor(which: 'A' | 'B') {
    const ms = cursorMs
    if (which === 'A') {
      // A must be < B; if setting A above current B, drop B.
      setLoopA(ms)
      if (loopB !== null && ms >= loopB) setLoopB(null)
    } else {
      if (loopA !== null && ms <= loopA) return
      setLoopB(ms)
    }
  }
  function clearLoop() {
    setLoopA(null)
    setLoopB(null)
    setLoopEnabled(false)
  }

  function generateFillActions(a: number, b: number): EditAction[] {
    const clamp = (v: number) => Math.max(0, Math.min(100, Math.round(v)))
    if (fillPattern === 'flat') {
      const p = clamp(fillHoldPos)
      return [
        { id: nextId(), at: a, pos: p },
        { id: nextId(), at: b, pos: p },
      ]
    }
    if (fillPattern === 'ramp') {
      return [
        { id: nextId(), at: a, pos: clamp(fillRampFrom) },
        { id: nextId(), at: b, pos: clamp(fillRampTo) },
      ]
    }
    // beat — alternate min/max at half-beat interval
    const bpm = Math.max(1, fillBeatBpm)
    const halfBeatMs = Math.max(10, Math.round(30000 / bpm))
    const lo = clamp(Math.min(fillBeatMin, fillBeatMax))
    const hi = clamp(Math.max(fillBeatMin, fillBeatMax))
    const out: EditAction[] = []
    let t = a
    let hi_ = true
    while (t <= b) {
      out.push({ id: nextId(), at: t, pos: hi_ ? hi : lo })
      hi_ = !hi_
      t += halfBeatMs
    }
    // Ensure a landing point exactly at B so the pattern doesn't
    // spill over or leave a gap before the next real action.
    if (out.length === 0 || out[out.length - 1].at !== b) {
      out.push({ id: nextId(), at: b, pos: hi_ ? hi : lo })
    }
    return out
  }

  function selectSection(idx: number) {
    if (!meta || !meta.sections[idx]) return
    const s = meta.sections[idx]
    setLoopA(s.start_ms)
    setLoopB(s.end_ms)
    if (videoRef.current) videoRef.current.currentTime = s.start_ms / 1000
  }

  function applyPatternToSection(secIdx: number, patternIdx: number) {
    if (!meta) return
    const s = meta.sections[secIdx]
    const pattern = meta.patterns[patternIdx]
    if (!s || !pattern || !pattern.some(Boolean)) return
    if (!confirm(
      `Replace beats in section ${secIdx + 1} `
      + `(${fmtMs(s.start_ms)}–${fmtMs(s.end_ms)}) `
      + `with pattern ${patternIdx + 1}?`,
    )) return
    // Emit a beat grid at the section's period, cycling the pattern.
    // Anchor on the section's stored anchor_ms so this matches how the
    // original generator laid the beats down.
    const newAts: number[] = []
    let t = s.anchor_ms
    while (t - s.period_ms >= s.start_ms) t -= s.period_ms
    let slot = 0
    while (t < s.end_ms) {
      if (pattern[slot % pattern.length]) newAts.push(Math.round(t))
      t += s.period_ms
      slot += 1
    }
    // Rebuild the actions inside [start, end] as strict trough/peak
    // reversals so the toy actually strokes. Match the section's period
    // to a max_down at the beat and max_up at the midpoint between beats
    // — same shape beat_actions would have produced.
    const generated: EditAction[] = []
    const troughPos = 0
    const peakPos = 100
    for (let i = 0; i < newAts.length; i++) {
      generated.push({ id: nextId(), at: newAts[i], pos: troughPos })
      const nextT = newAts[i + 1] ?? s.end_ms
      const midT = Math.round((newAts[i] + nextT) / 2)
      if (midT > newAts[i] && midT < nextT) {
        generated.push({ id: nextId(), at: midT, pos: peakPos })
      }
    }
    pushHistory()
    setActions((prev) => [
      ...prev.filter((x) => x.at < s.start_ms || x.at > s.end_ms),
      ...generated,
    ].sort((a, b) => a.at - b.at))
    setSelection(new Set(generated.map((x) => x.id)))
    setDirty(true)
  }

  function applyFillRange() {
    if (loopA === null || loopB === null || loopB <= loopA) return
    const a = loopA
    const b = loopB
    const newActs = generateFillActions(a, b)
    if (!confirm(
      `Replace all actions between ${fmtMs(a)} and ${fmtMs(b)} `
      + `with ${newActs.length} generated point${newActs.length === 1 ? '' : 's'}?`,
    )) return
    pushHistory()
    setActions((prev) =>
      [...prev.filter((x) => x.at < a || x.at > b), ...newActs]
        .sort((x, y) => x.at - y.at),
    )
    setSelection(new Set(newActs.map((x) => x.id)))
    setDirty(true)
  }

  async function reset() {
    if (!jobId || !job?.has_original) return
    if (!confirm('Reset to the auto-generated original? Unsaved edits will be lost.')) return
    setSaving(true)
    setError(null)
    try {
      await api.resetFunscript(jobId)
      const fs = await api.getFunscript(jobId)
      setActions(fs.actions.map((a) => ({ ...a, id: nextId() })))
      setSelection(new Set())
      setDirty(false)
      historyRef.current = []
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  keyHandlerRef.current = (e: KeyboardEvent) => {
    // Never hijack keys while the user is editing a form field.
    const t = e.target as HTMLElement | null
    if (
      t &&
      (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
    ) {
      return
    }
    const ctrl = e.ctrlKey || e.metaKey
    const hasSel = selection.size > 0

    if (ctrl && (e.key === 's' || e.key === 'S')) {
      e.preventDefault()
      if (dirty) save()
      return
    }
    if (ctrl && (e.key === 'z' || e.key === 'Z')) {
      e.preventDefault()
      undo()
      return
    }
    if (ctrl && (e.key === 'a' || e.key === 'A')) {
      e.preventDefault()
      selectAll()
      return
    }
    if (e.key === 'Delete' || e.key === 'Backspace') {
      if (hasSel) {
        e.preventDefault()
        deleteSelected()
      }
      return
    }
    if (e.key === 'Escape') {
      deselectAll()
      return
    }
    if (e.code === 'Space') {
      e.preventDefault()
      togglePlay()
      return
    }
    if (e.key === ',') {
      e.preventDefault()
      frameStep(e.shiftKey ? -10 : -1)
      return
    }
    if (e.key === '.') {
      e.preventDefault()
      frameStep(e.shiftKey ? 10 : 1)
      return
    }
    if (e.key === '1') { applyPlaybackRate(0.25); return }
    if (e.key === '2') { applyPlaybackRate(0.5); return }
    if (e.key === '3') { applyPlaybackRate(1); return }
    if (e.key === '4') { applyPlaybackRate(2); return }
    if (e.key === 'm' || e.key === 'M') { toggleMute(); return }
    if (e.key === 'i' || e.key === 'I') { setLoopFromCursor('A'); return }
    if (e.key === 'o' || e.key === 'O') { setLoopFromCursor('B'); return }
    if (e.key === 'l' || e.key === 'L') { setLoopEnabled((x) => !x); return }
    if (e.key === 'u' || e.key === 'U') { clearLoop(); return }
    if (e.key === '+' || e.key === '=') {
      setZoomIdx((i) => Math.min(ZOOM_LEVELS.length - 1, i + 1))
      return
    }
    if (e.key === '-' || e.key === '_') {
      setZoomIdx((i) => Math.max(0, i - 1))
      return
    }
    // Naked 's' toggles select mode. Positioned after Ctrl+S so it
    // doesn't collide with save.
    if (!ctrl && (e.key === 's' || e.key === 'S')) {
      setSelectMode((m) => !m)
      return
    }
    // Arrow keys: nudge selected if any, otherwise seek.
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      if (hasSel) nudge(e.shiftKey ? -100 : -10, 0)
      else seekBy(e.shiftKey ? -5000 : -1000)
      return
    }
    if (e.key === 'ArrowRight') {
      e.preventDefault()
      if (hasSel) nudge(e.shiftKey ? 100 : 10, 0)
      else seekBy(e.shiftKey ? 5000 : 1000)
      return
    }
    if (e.key === 'ArrowUp' && hasSel) {
      e.preventDefault()
      nudge(0, e.shiftKey ? 5 : 1)
      return
    }
    if (e.key === 'ArrowDown' && hasSel) {
      e.preventDefault()
      nudge(0, e.shiftKey ? -5 : -1)
      return
    }
  }

  if (error && !job) return <p className="p-4 text-red-400">{error}</p>
  if (!job || !video) return <p className="p-4 text-slate-400">Loading…</p>

  const selectedActions = actions.filter((a) => selection.has(a.id))
  const sel = selectedActions.length === 1 ? selectedActions[0] : null
  const pxPerSecond = ZOOM_LEVELS[zoomIdx]
  const currentFrame = Math.round((cursorMs / 1000) * (video.fps || 30))
  const totalFrames = Math.round((video.duration_ms / 1000) * (video.fps || 30))

  return (
    <div className="p-3 md:p-4 max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-2">
        <button
          onClick={() => {
            if (dirty && !confirm('Discard unsaved edits?')) return
            navigate('/jobs')
          }}
          className="text-sm text-slate-400 hover:text-slate-200"
        >
          ← Back
        </button>
        <p className="text-sm text-slate-400 truncate flex-1">{video.filename}</p>
        {dirty && <span className="text-xs text-amber-400">● unsaved</span>}
      </div>

      <div className="flex gap-3 items-stretch">
        <div
          className="relative bg-black flex-1"
          style={{
            aspectRatio: `${video.width} / ${video.height}`,
            maxWidth: `calc(40dvh * ${video.width / video.height})`,
          }}
        >
          {/* No native controls — they cover the bottom of the frame where
              beat bars live. Click anywhere on the video toggles play/pause;
              the strip below handles frame step, speed, mute, and time
              display. When a debug render exists, we use it as the source
              — it has algorithm overlays + event flashes, which makes it
              much easier to see if the funscript hits the right moments. */}
          <video
            ref={videoRef}
            src={job.debug_available ? api.debugUrl(job.id) : api.streamUrl(video.id)}
            className="w-full h-full cursor-pointer"
            preload="metadata"
            playsInline
            muted={muted}
            onClick={togglePlay}
          />
        </div>
        <StrokerVisualizer actions={actions} cursorMs={cursorMs} />
      </div>

      {/* Video scrubber — dedicated seek bar independent of the funscript
          timeline. Range input is touch-friendly and works on mobile. */}
      <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
        <span className="font-mono w-11 text-right">{fmtMs(cursorMs)}</span>
        <input
          type="range"
          min={0}
          max={Math.max(1, video.duration_ms)}
          step={10}
          value={cursorMs}
          onChange={(e) => {
            const t = parseInt(e.target.value, 10)
            if (videoRef.current) videoRef.current.currentTime = t / 1000
          }}
          className="flex-1 accent-indigo-500 touch-manipulation"
          aria-label="Scrub video"
        />
        <span className="font-mono w-11">{fmtMs(video.duration_ms)}</span>
      </div>

      {/* A/B loop strip — set A/B from current playback time, toggle
          loop, jump to A, clear. Loop enforces itself in the timeupdate
          handler above. */}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-slate-500">A/B loop</span>
        <button
          onClick={() => setLoopFromCursor('A')}
          className={`px-2 py-1 rounded font-mono ${
            loopA !== null ? 'bg-amber-600 text-white' : 'bg-slate-800 text-slate-300'
          }`}
          title="I — set A to current time"
        >
          A {loopA !== null ? fmtMs(loopA) : '—'}
        </button>
        <button
          onClick={() => setLoopFromCursor('B')}
          disabled={loopA === null || cursorMs <= (loopA ?? 0)}
          className={`px-2 py-1 rounded font-mono disabled:opacity-40 ${
            loopB !== null ? 'bg-amber-600 text-white' : 'bg-slate-800 text-slate-300'
          }`}
          title="O — set B to current time (must be after A)"
        >
          B {loopB !== null ? fmtMs(loopB) : '—'}
        </button>
        <button
          onClick={() => {
            if (loopA !== null && videoRef.current) {
              videoRef.current.currentTime = loopA / 1000
            }
          }}
          disabled={loopA === null}
          className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-40"
          title="Jump to A"
        >
          ⇱
        </button>
        <button
          onClick={() => setLoopEnabled((x) => !x)}
          disabled={loopA === null || loopB === null}
          className={`px-2 py-1 rounded disabled:opacity-40 ${
            loopEnabled
              ? 'bg-emerald-600 text-white'
              : 'bg-slate-800 text-slate-300'
          }`}
          title="L — toggle loop"
        >
          {loopEnabled ? 'Loop on' : 'Loop off'}
        </button>
        <button
          onClick={clearLoop}
          disabled={loopA === null && loopB === null}
          className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-40"
          title="U — clear loop"
        >
          Clear
        </button>
      </div>

      {/* Fill range — replace whatever's in [A,B] with a clean pattern.
          Meant for scrubbing out the jumble the algorithm emits in
          sections where no beat bar is actually visible on screen. */}
      {loopA !== null && loopB !== null && loopB > loopA && (
        <div className="mt-2 p-2 rounded-lg bg-slate-900 border border-slate-800">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-slate-500">Fill range</span>
            <select
              value={fillPattern}
              onChange={(e) => setFillPattern(e.target.value as 'flat' | 'beat' | 'ramp')}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1"
            >
              <option value="flat">Flat hold</option>
              <option value="beat">Steady beat</option>
              <option value="ramp">Linear ramp</option>
            </select>
            {fillPattern === 'flat' && (
              <label className="flex items-center gap-1">
                <span className="text-slate-400">Pos</span>
                <input
                  type="number" min={0} max={100}
                  value={fillHoldPos}
                  onChange={(e) => setFillHoldPos(parseInt(e.target.value, 10) || 0)}
                  className="w-14 bg-slate-800 border border-slate-700 rounded px-1.5 py-1 font-mono"
                />
              </label>
            )}
            {fillPattern === 'beat' && (
              <>
                <label className="flex items-center gap-1">
                  <span className="text-slate-400">BPM</span>
                  <input
                    type="number" min={1} max={600}
                    value={fillBeatBpm}
                    onChange={(e) => setFillBeatBpm(parseInt(e.target.value, 10) || 60)}
                    className="w-14 bg-slate-800 border border-slate-700 rounded px-1.5 py-1 font-mono"
                  />
                </label>
                <label className="flex items-center gap-1">
                  <span className="text-slate-400">Min</span>
                  <input
                    type="number" min={0} max={100}
                    value={fillBeatMin}
                    onChange={(e) => setFillBeatMin(parseInt(e.target.value, 10) || 0)}
                    className="w-14 bg-slate-800 border border-slate-700 rounded px-1.5 py-1 font-mono"
                  />
                </label>
                <label className="flex items-center gap-1">
                  <span className="text-slate-400">Max</span>
                  <input
                    type="number" min={0} max={100}
                    value={fillBeatMax}
                    onChange={(e) => setFillBeatMax(parseInt(e.target.value, 10) || 0)}
                    className="w-14 bg-slate-800 border border-slate-700 rounded px-1.5 py-1 font-mono"
                  />
                </label>
              </>
            )}
            {fillPattern === 'ramp' && (
              <>
                <label className="flex items-center gap-1">
                  <span className="text-slate-400">From</span>
                  <input
                    type="number" min={0} max={100}
                    value={fillRampFrom}
                    onChange={(e) => setFillRampFrom(parseInt(e.target.value, 10) || 0)}
                    className="w-14 bg-slate-800 border border-slate-700 rounded px-1.5 py-1 font-mono"
                  />
                </label>
                <label className="flex items-center gap-1">
                  <span className="text-slate-400">To</span>
                  <input
                    type="number" min={0} max={100}
                    value={fillRampTo}
                    onChange={(e) => setFillRampTo(parseInt(e.target.value, 10) || 0)}
                    className="w-14 bg-slate-800 border border-slate-700 rounded px-1.5 py-1 font-mono"
                  />
                </label>
              </>
            )}
            <button
              onClick={applyFillRange}
              className="ml-auto px-3 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-medium"
              title="Delete actions in the A/B range and insert the pattern"
            >
              Apply
            </button>
          </div>
        </div>
      )}

      {/* Video controls: frame step + playback speed. Under the video,
          above the timeline. Native <video controls> keeps play/pause/scrub;
          this strip adds what browsers don't give us out of the box. */}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        <button
          onClick={() => frameStep(-1)}
          className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 font-mono"
          title=", (comma) — previous frame; Shift+, jumps 10"
        >
          ◄ 1f
        </button>
        <button
          onClick={togglePlay}
          className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700"
          title="Space — play/pause"
        >
          ⏵/⏸
        </button>
        <button
          onClick={() => frameStep(+1)}
          className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 font-mono"
          title=". (period) — next frame; Shift+. jumps 10"
        >
          1f ►
        </button>
        <div className="flex items-center gap-1 ml-2">
          <span className="text-slate-500 text-xs mr-1">Speed</span>
          {[0.25, 0.5, 1, 2].map((r) => (
            <button
              key={r}
              onClick={() => applyPlaybackRate(r)}
              className={`px-2 py-1 rounded text-xs font-mono ${
                playbackRate === r
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-800 text-slate-300'
              }`}
              title={`Keyboard: ${r === 0.25 ? '1' : r === 0.5 ? '2' : r === 1 ? '3' : '4'}`}
            >
              {r}×
            </button>
          ))}
        </div>
        <button
          onClick={toggleMute}
          className="px-2 py-1.5 rounded bg-slate-800 hover:bg-slate-700 ml-2"
          title="M — mute / unmute"
        >
          {muted ? '🔇' : '🔊'}
        </button>
        <span className="ml-auto text-xs text-slate-500 font-mono">
          {fmtMs(cursorMs)} / {fmtMs(video.duration_ms)} · frame {currentFrame}/{totalFrames}
        </span>
      </div>

      {/* Zoom controls sit right above the timeline where you look when
          you actually want to zoom. Ctrl+wheel on the timeline itself
          also zooms; keyboard +/- as before. */}
      <div className="mt-3 flex items-center gap-2 text-sm">
        <span className="text-slate-500 mr-1">Timeline zoom</span>
        <button
          onClick={() => setZoomIdx((i) => Math.max(0, i - 1))}
          disabled={zoomIdx === 0}
          className="w-8 h-8 rounded bg-slate-700 disabled:opacity-40"
          title="Zoom out — keyboard: - or Ctrl+wheel"
        >
          −
        </button>
        <span className="w-16 text-center font-mono text-xs text-slate-400">
          {pxPerSecond} px/s
        </span>
        <button
          onClick={() => setZoomIdx((i) => Math.min(ZOOM_LEVELS.length - 1, i + 1))}
          disabled={zoomIdx === ZOOM_LEVELS.length - 1}
          className="w-8 h-8 rounded bg-slate-700 disabled:opacity-40"
          title="Zoom in — keyboard: + or Ctrl+wheel"
        >
          +
        </button>
        <span className="ml-auto text-xs text-slate-500 hidden md:inline">
          Ctrl + scroll wheel zooms directly
        </span>
      </div>

      <div className="mt-1">
        <TimelineGraph
          actions={actions}
          durationMs={video.duration_ms}
          pxPerSecond={pxPerSecond}
          cursorMs={cursorMs}
          selection={selection}
          selectMode={selectMode}
          onPointDown={onPointDown}
          onDragDelta={onDragDelta}
          onDragEnd={onDragEnd}
          onEmptyTap={onEmptyTap}
          onRubberBand={onRubberBand}
          onZoomStep={(dir) =>
            setZoomIdx((i) =>
              Math.max(0, Math.min(ZOOM_LEVELS.length - 1, i + dir)),
            )
          }
          sectionBoundariesMs={meta?.sections.flatMap((s) => [s.start_ms, s.end_ms])}
        />
      </div>

      {/* Sections — audio-mode metadata. Each button jumps to the
          section and sets A/B loop to it. When patterns exist, a
          "→ pat N" mini-button re-generates that section's beats
          using pattern N. */}
      {meta && meta.sections.length > 0 && (
        <div className="mt-3 p-2 rounded-lg bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs uppercase tracking-wide text-slate-500">
              Sections ({meta.sections.length})
            </p>
            {job.mode === 'audio' && (
              <button
                onClick={rerenderDebug}
                disabled={rerendering}
                className="px-2 py-1 rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40 text-xs"
                title="Rebuild the beat-bar video from the current funscript so it matches your section edits"
              >
                {rerendering
                  ? `Rebuilding… ${Math.round(rerenderProgress * 100)}%`
                  : 'Rebuild beat-bar video'}
              </button>
            )}
          </div>
          <div className="flex flex-col gap-2">
            {meta.sections.map((s, i) => {
              const inRange = cursorMs >= s.start_ms && cursorMs < s.end_ms
              const active = loopA === s.start_ms && loopB === s.end_ms
              return (
                <div
                  key={i}
                  className={`flex flex-wrap items-center gap-2 p-2 rounded border text-xs ${
                    active
                      ? 'bg-amber-500/10 border-amber-500/40'
                      : inRange
                        ? 'bg-slate-800 border-slate-700'
                        : 'bg-slate-900 border-slate-800'
                  }`}
                >
                  <button
                    onClick={() => selectSection(i)}
                    className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 font-mono"
                    title="Jump to section and set A/B loop to it"
                  >
                    §{i + 1}
                  </button>
                  <span className="font-mono text-slate-400">
                    {fmtMs(s.start_ms)}–{fmtMs(s.end_ms)}
                  </span>
                  <span className="font-mono text-slate-500">
                    period {s.period_ms}ms
                  </span>
                  {s.pattern_index !== null && (
                    <span className="font-mono text-slate-500">
                      pat {s.pattern_index + 1}
                    </span>
                  )}
                  {meta.patterns.length > 0 && (
                    <div className="ml-auto flex flex-wrap gap-1">
                      {meta.patterns.map((_p, pIdx) => (
                        <button
                          key={pIdx}
                          onClick={() => applyPatternToSection(i, pIdx)}
                          className="px-2 py-1 rounded bg-indigo-700/70 hover:bg-indigo-600 font-mono"
                          title={`Replace section ${i + 1} beats with pattern ${pIdx + 1}`}
                        >
                          → pat {pIdx + 1}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Mode + quick-select bar */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          onClick={() => setSelectMode((s) => !s)}
          className={`px-3 py-2 rounded text-sm font-medium ${
            selectMode
              ? 'bg-amber-500 text-slate-900'
              : 'bg-slate-700 text-slate-100'
          }`}
        >
          {selectMode ? 'Select mode: on' : 'Select mode'}
        </button>
        <button onClick={selectPeaks} className="px-3 py-2 rounded text-sm bg-slate-800">
          Peaks (≥80)
        </button>
        <button onClick={selectTroughs} className="px-3 py-2 rounded text-sm bg-slate-800">
          Troughs (≤20)
        </button>
        <button onClick={selectAll} className="px-3 py-2 rounded text-sm bg-slate-800">
          All
        </button>
        <button
          onClick={deselectAll}
          disabled={selection.size === 0}
          className="px-3 py-2 rounded text-sm bg-slate-800 disabled:opacity-40"
        >
          None
        </button>
        <span className="ml-auto text-xs text-slate-500 font-mono">
          {selection.size} selected
        </span>
      </div>

      {/* Selection info + nudge pad */}
      <div className="mt-3 p-3 rounded-lg bg-slate-900 border border-slate-800">
        {selection.size === 0 ? (
          <p className="text-sm text-slate-500">
            {selectMode
              ? 'Drag a rectangle over the timeline to rubber-band select. Tap a point to toggle. Use Peaks / Troughs for bulk selection.'
              : 'Tap a point to select it, or tap the empty timeline to add one. Turn on Select mode for multi-select.'}
          </p>
        ) : (
          <>
            <div className="flex justify-between items-center mb-2 gap-4 flex-wrap">
              {sel ? (
                <div className="flex items-center gap-3 text-sm">
                  <label className="flex items-center gap-2">
                    <span className="text-slate-400">Time</span>
                    <input
                      type="number"
                      min={0}
                      value={sel.at}
                      onChange={(e) => setSelectedAt(parseInt(e.target.value, 10) || 0)}
                      className="w-20 bg-slate-800 border border-slate-700 rounded px-2 py-1 font-mono text-sm"
                    />
                    <span className="text-slate-500 font-mono text-xs">{fmtMs(sel.at)}</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <span className="text-slate-400">Pos</span>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={sel.pos}
                      onChange={(e) => setSelectedPos(parseInt(e.target.value, 10) || 0)}
                      className="w-16 bg-slate-800 border border-slate-700 rounded px-2 py-1 font-mono text-sm"
                    />
                  </label>
                </div>
              ) : (
                <p className="text-sm">
                  <span className="text-amber-400 font-mono">{selection.size}</span>{' '}
                  <span className="text-slate-400">selected · nudge & delete apply to all</span>
                </p>
              )}
              <button
                onClick={deleteSelected}
                className="px-3 py-1.5 rounded text-sm bg-red-900/70 hover:bg-red-900"
              >
                Delete{selection.size > 1 ? ` ${selection.size}` : ''}
              </button>
            </div>
            <div className="grid grid-cols-4 gap-2">
              <NudgeBtn label="Pos −5" onClick={() => nudge(0, -5)} />
              <NudgeBtn label="Pos −1" onClick={() => nudge(0, -1)} />
              <NudgeBtn label="Pos +1" onClick={() => nudge(0, +1)} />
              <NudgeBtn label="Pos +5" onClick={() => nudge(0, +5)} />
              <NudgeBtn label="Time −100" onClick={() => nudge(-100, 0)} />
              <NudgeBtn label="Time −10" onClick={() => nudge(-10, 0)} />
              <NudgeBtn label="Time +10" onClick={() => nudge(+10, 0)} />
              <NudgeBtn label="Time +100" onClick={() => nudge(+100, 0)} />
            </div>
          </>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-2 items-center">
        <button
          onClick={save}
          disabled={saving || !dirty}
          className="px-4 py-2 rounded bg-emerald-600 disabled:opacity-40 text-sm font-medium"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          onClick={undo}
          disabled={historyRef.current.length === 0}
          className="px-4 py-2 rounded bg-slate-700 disabled:opacity-40 text-sm"
        >
          Undo
        </button>
        <button
          onClick={reset}
          disabled={saving || !job.has_original}
          title={job.has_original ? '' : 'No original snapshot yet — save at least once first.'}
          className="px-4 py-2 rounded bg-slate-700 disabled:opacity-40 text-sm"
        >
          Reset to original
        </button>
      </div>

      <p className="mt-3 text-xs text-slate-500">
        {actions.length} action{actions.length === 1 ? '' : 's'} · duration{' '}
        {fmtMs(video.duration_ms)}
      </p>

      <details className="mt-3 text-xs text-slate-400 select-none">
        <summary className="cursor-pointer text-slate-500 hover:text-slate-300">
          Keyboard shortcuts
        </summary>
        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1 pl-3">
          <Shortcut k="Space" v="Play / pause" />
          <Shortcut k=", / ." v="Prev / next frame (Shift = ×10)" />
          <Shortcut k="1 / 2 / 3 / 4" v="Speed 0.25× / 0.5× / 1× / 2×" />
          <Shortcut k="M" v="Mute / unmute" />
          <Shortcut k="I / O" v="Set loop A / B at cursor" />
          <Shortcut k="L" v="Toggle A/B loop playback" />
          <Shortcut k="U" v="Clear A/B loop" />
          <Shortcut k="+ / −" v="Zoom in / out" />
          <Shortcut k="S" v="Toggle Select mode" />
          <Shortcut k="←/→" v="Nudge time (selected) — Shift = ×10 — else seek 1s" />
          <Shortcut k="↑/↓" v="Nudge position (selected) — Shift = ×5" />
          <Shortcut k="Del / Backspace" v="Delete selected" />
          <Shortcut k="Esc" v="Deselect all" />
          <Shortcut k="Ctrl+S" v="Save" />
          <Shortcut k="Ctrl+Z" v="Undo" />
          <Shortcut k="Ctrl+A" v="Select all" />
        </div>
      </details>

      {error && <p className="mt-3 text-sm text-red-400 break-words">{error}</p>}
    </div>
  )
}

function Shortcut({ k, v }: { k: string; v: string }) {
  return (
    <p className="flex gap-3">
      <span className="font-mono text-slate-300 whitespace-nowrap">{k}</span>
      <span>{v}</span>
    </p>
  )
}

function NudgeBtn({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="py-2 rounded bg-slate-800 hover:bg-slate-700 active:bg-slate-600 text-sm touch-manipulation"
    >
      {label}
    </button>
  )
}
