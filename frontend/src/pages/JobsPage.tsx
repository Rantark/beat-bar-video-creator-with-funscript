import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Job, VideoMeta } from '../types'
import { fmtMs } from '../util'

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [videos, setVideos] = useState<Record<string, VideoMeta>>({})
  const [error, setError] = useState<string | null>(null)

  async function reload() {
    try {
      const [js, vs] = await Promise.all([api.listJobs(), api.listVideos()])
      setJobs(js)
      setVideos(Object.fromEntries(vs.map((v) => [v.id, v])))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [js, vs] = await Promise.all([api.listJobs(), api.listVideos()])
        if (cancelled) return
        setJobs(js)
        setVideos(Object.fromEntries(vs.map((v) => [v.id, v])))
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      }
    }
    load()
    // Poll while any job is still in flight — cheap on single-user DB.
    const t = window.setInterval(load, 1000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [])

  async function deleteJob(id: string) {
    if (!confirm(
      'Delete this job? Removes the funscript, debug MP4 (if any), and edit backup. ' +
      'The source video is kept — delete it from the Videos tab if you also want that.',
    )) return
    try {
      await api.deleteJob(id)
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  if (error) return <p className="p-4 text-red-400">{error}</p>
  if (!jobs) return <p className="p-4 text-slate-400">Loading…</p>
  if (jobs.length === 0)
    return <p className="p-6 text-center text-slate-400">No jobs yet.</p>

  return (
    <ul className="divide-y divide-slate-800 max-w-3xl mx-auto">
      {jobs.map((job) => {
        const v = videos[job.video_id]
        return (
          <li key={job.id} className="p-4">
            <div className="flex justify-between items-start gap-4">
              <div className="min-w-0 flex-1">
                <p className="font-medium truncate">{v?.filename ?? job.video_id}</p>
                <p className="text-sm text-slate-400">
                  {job.mode} · {v ? fmtMs(v.duration_ms) : '—'}
                </p>
                <p className="text-sm mt-1">
                  <StatusBadge status={job.status} />
                  {job.status === 'processing' && (
                    <span className="ml-2 text-slate-400 font-mono">
                      {Math.round(job.progress * 100)}%
                    </span>
                  )}
                </p>
                {job.status === 'processing' && (
                  <div className="mt-2 h-1.5 bg-slate-800 rounded">
                    <div
                      className="h-1.5 bg-indigo-500 rounded transition-all"
                      style={{ width: `${job.progress * 100}%` }}
                    />
                  </div>
                )}
                {job.status === 'failed' && job.error && (
                  <pre className="mt-2 text-xs text-red-400 whitespace-pre-wrap break-words max-h-32 overflow-auto">
                    {job.error}
                  </pre>
                )}
              </div>
              <div className="flex flex-col gap-2 shrink-0">
                {job.status === 'done' && (
                  <a
                    href={api.downloadUrl(job.id)}
                    className="px-3 py-2 rounded text-sm text-center bg-emerald-600"
                  >
                    Download
                  </a>
                )}
                {job.status === 'done' && (
                  <Link
                    to={`/edit/${job.id}`}
                    className="px-3 py-2 rounded text-sm text-center bg-amber-600"
                  >
                    Edit
                  </Link>
                )}
                {job.status === 'done' && job.debug_available && (
                  <a
                    href={api.debugUrl(job.id)}
                    className="px-3 py-2 rounded text-sm text-center bg-indigo-600"
                  >
                    Debug MP4
                  </a>
                )}
                <Link
                  to={`/frame/${job.video_id}`}
                  className="px-3 py-2 rounded text-sm text-center bg-slate-700"
                >
                  Re-run
                </Link>
                <button
                  onClick={() => deleteJob(job.id)}
                  className="px-3 py-2 rounded text-sm text-center bg-red-900/70 hover:bg-red-900"
                >
                  Delete
                </button>
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function StatusBadge({ status }: { status: Job['status'] }) {
  const cls =
    status === 'done'
      ? 'bg-emerald-800 text-emerald-200'
      : status === 'processing'
      ? 'bg-indigo-800 text-indigo-200'
      : status === 'failed'
      ? 'bg-red-900 text-red-200'
      : 'bg-slate-700 text-slate-200'
  return (
    <span className={`text-xs uppercase tracking-wide px-2 py-0.5 rounded ${cls}`}>
      {status}
    </span>
  )
}
