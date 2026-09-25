export type VideoMeta = {
  id: string
  filename: string
  size_bytes: number
  duration_ms: number
  width: number
  height: number
  fps: number
  sprite_ready: boolean
  sprite_cols: number | null
  sprite_rows: number | null
  sprite_interval_ms: number | null
  sprite_thumb_width: number | null
  sprite_thumb_height: number | null
  created_at: string
  // Present when the video was pulled by URL rather than uploaded.
  source_type: 'upload' | 'url'
  source_url: string | null
  download_status: 'queued' | 'downloading' | 'ready' | 'failed' | null
  download_progress: number
  download_error: string | null
}

export type Zone = { x: number; y: number; w: number; h: number }
export type Line = {
  orientation: 'horizontal' | 'vertical'
  x: number       // center X of the line, normalized 0..1
  y: number       // center Y of the line, normalized 0..1
  length: number  // extent along the orientation axis, normalized 0..1
  // Same shape/musical/smoothing knobs as marker mode — crossings ARE
  // beats, so they flow through the same downstream pipeline.
  max_up: number
  max_up_fast: number
  max_down_fast: number
  max_down: number
  variety_amount: number
  idle_enabled: boolean
  motion_smoothing: number
}
export type Marker = {
  x: number       // normalized center X, 0..1
  y: number       // normalized center Y, 0..1
  radius: number  // fraction of min(video_width, video_height), 0.005..0.1
  // Stroke-shape params. Both ends interpolate by speed:
  //   fast stroke → max_up_fast / max_down_fast
  //   slow stroke → max_up      / max_down
  // Constraint: max_down ≤ max_down_fast ≤ max_up_fast ≤ max_up.
  // To make only the downstroke vary, set max_up_fast = max_up.
  max_up: number
  max_up_fast: number
  max_down_fast: number
  max_down: number
  // Cross-section variety (0..1). 0 = every rhythmic section uses the
  // same tempo target; 1 = sections randomize their sub-range within
  // the target envelope. Seeded from the beat pattern → deterministic.
  variety_amount: number
  // Slow oscillation during quiet gaps (start, between sections, end).
  // Off = the toy stays still in silent gaps.
  idle_enabled: boolean
  // Beat detection sensitivity (0..1). 0 = strict (only strong beats
  // count), 0.5 = default prominence 15, 1 = permissive (catches faint
  // beats but risks more noise).
  sensitivity: number
  // Motion smoothing 0..4. 0 = raw triangle wave (abrupt reversals).
  // 2-3 = S-curve motion around each peak/trough via smoothstep points.
  motion_smoothing: number
  // Optional base64 data URL (data:image/png;base64,...) captured from
  // a video frame at the marker location. When present, backend adds
  // template-matching scores as an extra signal component.
  template: string | null
}

// Kept in sync with LineProcessor's strip fraction. Only detection
// inside the line's extent + this much perpendicular tolerance counts,
// so distant background motion can't steal tracking.
export const LINE_STRIP_FRACTION = 0.2

// Pose-driven detection. No spatial placement — the neural body-
// keypoint tracker (YOLOv8-pose) finds the person automatically.
// Requires the [pose] optional backend install.
export type Pose = {
  // Which of the 17 COCO keypoints drives the funscript. "auto" picks
  // the keypoint whose vertical position moves the most across the
  // clip — usually the right answer for whole-body rhythmic content.
  keypoint: string          // "auto" or a keypoint name
  axis: 'y' | 'x' | 'magnitude'
  confidence_threshold: number  // 0..1; per-frame detection min conf
  invert: boolean
  resize_max: number        // long-edge cap for inference (speed knob)
}

export const POSE_KEYPOINTS = [
  'auto',
  'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
  'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
  'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
  'left_knee', 'right_knee', 'left_ankle', 'right_ankle',
] as const

// Audio-driven mode. No spatial placement — the whole thing runs off
// the source's audio track. Rhythm knobs are shared with marker/line
// via the same beat_actions pipeline on the backend.
export type Audio = {
  sensitivity: number   // 0..1 onset threshold (1 = permissive)
  min_gap_ms: number    // refractory period between onsets
  low_hz: number        // spectral band low edge
  high_hz: number       // spectral band high edge
  // Learned beat tracker (librosa) instead of raw spectral-flux
  // peak-picking. Handles tempo changes, syncopation, and quiet
  // passages more accurately. Requires the [neural] optional install.
  use_neural: boolean
  // Rigidity of the beat-picker's tempo prior. Higher = the picker
  // sticks harder to the estimated tempo, useful when a song has a
  // steady beat under a busy surface.
  neural_tightness: number
  // Regularization: split the track into ~section_target_ms windows,
  // lock a steady tempo per window, emit a phase-aligned grid. Turns
  // spontaneous onset detection into a rhythm-game-style chart with
  // consistent beats inside each section and clean tempo shifts at
  // section boundaries. Off = raw onsets pass straight through.
  regularize: boolean
  // All section lengths land on 5-second multiples between min and max,
  // biased around target. section_fluctuation (0..1) controls how much
  // per-section length varies from the target — 0 = every section is
  // exactly target, 1 = uniform across [min, max].
  section_min_ms: number
  section_target_ms: number
  section_max_ms: number
  section_fluctuation: number
  // Per-section pattern variety. When > 0, some sections switch to
  // half-time or double-time (2× or 0.5× the section's dominant beat
  // period) so consecutive sections feel rhythmically different even
  // when the music holds a steady tempo.
  pattern_variety: number
  // User-defined beat patterns applied inside sections. Each pattern
  // is a fixed-length array of slots; each slot carries its own
  // on/off flag plus max_up / max_down depth so a single pattern can
  // mix shallow and deep strokes. Backend picks one pattern per
  // section and emits actions using per-slot depth, so consecutive
  // sections feel rhythmically AND texturally different.
  patterns: BeatPattern[]
  // Rhythm-game debug overlay: beats scroll right→left across this
  // strip and cross the hit marker at exactly their onset time.
  lookahead_ms: number  // how far ahead the bar shows upcoming beats
  bar_image: string | null   // background of the beat bar (opaque)
  hit_image: string | null   // fixed hit-marker sprite (transparent OK)
  beat_image: string | null  // per-beat sprite (transparent OK)
  // Global stroke-shape fallbacks. Individual pattern slots override
  // these via their own max_up / max_down; unpatterned sections use
  // the global values through the beat_actions pipeline.
  max_up: number
  max_up_fast: number
  max_down_fast: number
  max_down: number
  variety_amount: number
  idle_enabled: boolean
  motion_smoothing: number
}

export type PatternSlot = {
  on: boolean
  max_up: number    // 0..100, position at the midpoint upstroke for this slot
  max_down: number  // 0..100, position at the beat trough for this slot
}

export type BeatPattern = {
  slots: PatternSlot[]
}

export type Job = {
  id: string
  video_id: string
  mode: 'zone' | 'line' | 'marker' | 'audio' | 'pose' | 'imported'
  params: Record<string, unknown>
  status: 'queued' | 'processing' | 'done' | 'failed'
  progress: number
  error: string | null
  created_at: string
  updated_at: string
  debug_available: boolean
  has_original: boolean
}

export type UploadInit = {
  upload_id: string
  chunk_size: number
  total_chunks: number
  received_chunks: number[]
}

export type Action = { at: number; pos: number }
export type Funscript = { version: string; actions: Action[] }

// Audio-mode job metadata persisted alongside the funscript. Lets the
// editor draw section boundaries and re-apply patterns to a section
// without regenerating the whole job.
export type JobSection = {
  start_ms: number
  end_ms: number
  period_ms: number
  anchor_ms: number
  pattern_index: number | null
}

export type JobMeta = {
  sections: JobSection[]
  patterns: BeatPattern[]
}

export type Preset = {
  id: string
  name: string
  mode: 'marker' | 'line'
  params: Record<string, unknown>
  created_at: string
  updated_at: string
}
