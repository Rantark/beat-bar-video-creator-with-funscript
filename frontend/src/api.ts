import type { Action, Funscript, Job, JobMeta, Preset, UploadInit, VideoMeta } from './types'

// All routes go through /api so Vite's dev proxy and the eventual
// prod static-serving path both work with the same client code.
const BASE = '/api'

async function j<T>(res: Response, label: string): Promise<T> {
  if (!res.ok) throw new Error(`${label} failed: ${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

export const api = {
  health: () => fetch(`${BASE}/health`).then(r => j<{ status: string }>(r, 'health')),

  listVideos: () => fetch(`${BASE}/videos`).then(r => j<VideoMeta[]>(r, 'listVideos')),

  getVideo: (id: string) =>
    fetch(`${BASE}/videos/${id}`).then(r => j<VideoMeta>(r, 'getVideo')),

  deleteVideo: (id: string) =>
    fetch(`${BASE}/videos/${id}`, { method: 'DELETE' })
      .then(r => j<{ ok: boolean }>(r, 'deleteVideo')),

  listJobs: () => fetch(`${BASE}/jobs`).then(r => j<Job[]>(r, 'listJobs')),

  getJob: (id: string) => fetch(`${BASE}/jobs/${id}`).then(r => j<Job>(r, 'getJob')),

  deleteJob: (id: string) =>
    fetch(`${BASE}/jobs/${id}`, { method: 'DELETE' })
      .then(r => j<{ ok: boolean; removed: string[] }>(r, 'deleteJob')),

  createJob: (payload: {
    video_id: string
    mode: 'zone' | 'line' | 'marker' | 'audio'
    params: Record<string, unknown>
  }) =>
    fetch(`${BASE}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => j<{ job_id: string }>(r, 'createJob')),

  initUpload: (payload: { filename: string; total_size: number; chunk_size?: number }) =>
    fetch(`${BASE}/uploads/init`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => j<UploadInit>(r, 'initUpload')),

  uploadChunk: (uploadId: string, index: number, chunk: Blob) =>
    fetch(`${BASE}/uploads/${uploadId}/chunks/${index}`, { method: 'PUT', body: chunk })
      .then(r => j<{ received: number[] }>(r, 'uploadChunk')),

  finalizeUpload: (uploadId: string) =>
    fetch(`${BASE}/uploads/${uploadId}/finalize`, { method: 'POST' })
      .then(r => j<{ video_id: string }>(r, 'finalizeUpload')),

  uploadFromUrl: (payload: {
    url: string
    quality?: '1080p' | '720p' | '480p' | 'best'
    cookies_browser?: string | null
    cookies_txt?: string | null
  }) =>
    fetch(`${BASE}/uploads/from-url`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => j<{ video_id: string }>(r, 'uploadFromUrl')),

  uploadFromPath: (payload: { path: string }) =>
    fetch(`${BASE}/uploads/from-path`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => j<{ video_id: string }>(r, 'uploadFromPath')),

  // Editor endpoints. The existing /download URL returns the funscript
  // as JSON (Content-Type: application/json), so getFunscript reuses it.
  getFunscript: (jobId: string) =>
    fetch(`${BASE}/jobs/${jobId}/download`).then(r => j<Funscript>(r, 'getFunscript')),

  saveFunscript: (jobId: string, actions: Action[]) =>
    fetch(`${BASE}/jobs/${jobId}/funscript`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actions }),
    }).then(r => j<{ ok: boolean; action_count: number; has_original: boolean }>(r, 'saveFunscript')),

  getJobMeta: (jobId: string) =>
    fetch(`${BASE}/jobs/${jobId}/meta`).then(async (r) => {
      if (r.status === 404) return null
      if (!r.ok) throw new Error(`getJobMeta failed: ${r.status}`)
      return (await r.json()) as JobMeta
    }),

  resetFunscript: (jobId: string) =>
    fetch(`${BASE}/jobs/${jobId}/funscript/reset`, { method: 'POST' })
      .then(r => j<{ ok: boolean }>(r, 'resetFunscript')),

  rerenderDebug: (jobId: string) =>
    fetch(`${BASE}/jobs/${jobId}/rerender-debug`, { method: 'POST' })
      .then(r => j<{ ok: boolean }>(r, 'rerenderDebug')),

  listPresets: (mode?: 'marker' | 'line') =>
    fetch(`${BASE}/presets${mode ? `?mode=${mode}` : ''}`)
      .then(r => j<Preset[]>(r, 'listPresets')),

  createPreset: (payload: {
    name: string
    mode: 'marker' | 'line'
    params: Record<string, unknown>
  }) =>
    fetch(`${BASE}/presets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => j<Preset>(r, 'createPreset')),

  updatePreset: (id: string, payload: { name?: string; params?: Record<string, unknown> }) =>
    fetch(`${BASE}/presets/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => j<Preset>(r, 'updatePreset')),

  deletePreset: (id: string) =>
    fetch(`${BASE}/presets/${id}`, { method: 'DELETE' })
      .then(r => j<{ ok: boolean }>(r, 'deletePreset')),

  importFunscript: (videoId: string, actions: Action[]) =>
    fetch(`${BASE}/jobs/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: videoId, actions }),
    }).then(r => j<{ job_id: string; action_count: number }>(r, 'importFunscript')),

  downloadUrl: (jobId: string) => `${BASE}/jobs/${jobId}/download`,
  debugUrl: (jobId: string) => `${BASE}/jobs/${jobId}/debug`,
  streamUrl: (videoId: string) => `${BASE}/videos/${videoId}/stream`,
  spriteUrl: (videoId: string) => `${BASE}/videos/${videoId}/sprite`,
}
