import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { VideoMeta } from '../types'
import { fmtBytes, fmtMs } from '../util'

export default function HomePage() {
  const [videos, setVideos] = useState<VideoMeta[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    try {
      setVideos(await api.listVideos())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }
  useEffect(() => {
    load()
    // Refresh periodically so a URL download's progress advances without
    // requiring a manual reload. Cheap — the endpoint is small.
    const t = window.setInterval(load, 1500)
    return () => clearInterval(t)
  }, [])

  async function del(id: string) {
    if (!confirm('Delete this video and all its jobs?')) return
    await api.deleteVideo(id)
    load()
  }

  if (error) return <p className="p-4 text-red-400">{error}</p>
  if (!videos) return <p className="p-4 text-slate-400">Loading…</p>

  if (videos.length === 0) {
    return (
      <div className="p-6 text-center">
        <p className="text-slate-400 mb-4">No videos yet.</p>
        <Link
          to="/upload"
          className="inline-block px-6 py-3 rounded-lg bg-indigo-600 text-lg"
        >
          Upload one
        </Link>
      </div>
    )
  }

  return (
    <ul className="divide-y divide-slate-800 max-w-3xl mx-auto">
      {videos.map((v) => (
        <li key={v.id} className="p-4">
          <div className="flex justify-between items-start gap-4">
            <div className="min-w-0 flex-1">
              <p className="font-medium truncate">{v.filename}</p>
              <p className="text-sm text-slate-400 font-mono">
                {v.duration_ms ? fmtMs(v.duration_ms) : '—'}
                {v.width ? ` · ${v.width}×${v.height}` : ''}
                {v.size_bytes ? ` · ${fmtBytes(v.size_bytes)}` : ''}
              </p>
              {v.source_type === 'url' && v.download_status &&
                v.download_status !== 'ready' && (
                <p className="text-xs text-amber-400 mt-1">
                  {v.download_status === 'queued' && 'Queued for download…'}
                  {v.download_status === 'downloading' &&
                    `Downloading ${Math.round((v.download_progress || 0) * 100)}%`}
                  {v.download_status === 'failed' && 'Download failed'}
                </p>
              )}
              {v.download_status !== 'downloading' &&
                v.download_status !== 'queued' &&
                v.download_status !== 'failed' &&
                !v.sprite_ready && (
                <p className="text-xs text-amber-400 mt-1">Sprite generating…</p>
              )}
            </div>
            <div className="flex flex-col gap-2 shrink-0">
              <Link
                to={`/frame/${v.id}`}
                className={`px-3 py-2 rounded text-sm text-center ${
                  v.sprite_ready ? 'bg-indigo-600' : 'bg-slate-700 pointer-events-none opacity-50'
                }`}
              >
                New job
              </Link>
              <button
                onClick={() => del(v.id)}
                className="px-3 py-2 rounded text-sm bg-red-900/60"
              >
                Delete
              </button>
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}
