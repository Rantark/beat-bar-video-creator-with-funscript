import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { fmtBytes } from '../util'

type Tab = 'local' | 'url' | 'import'
type UploadStatus = 'idle' | 'uploading' | 'finalizing' | 'done' | 'error'

// Only offer the paste-local-path fast lane when the frontend is
// served from the same machine as the backend. From a phone via
// Tailscale, the path would be meaningless.
const isLocalHost =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1')

export default function UploadPage() {
  const [tab, setTab] = useState<Tab>('local')
  return (
    <div className="p-4 max-w-md md:max-w-lg mx-auto">
      <div className="flex gap-1 p-1 bg-slate-900 rounded-lg border border-slate-800 mb-4">
        <TabButton active={tab === 'local'} onClick={() => setTab('local')}>
          Local file
        </TabButton>
        <TabButton active={tab === 'url'} onClick={() => setTab('url')}>
          From URL
        </TabButton>
        <TabButton active={tab === 'import'} onClick={() => setTab('import')}>
          Import script
        </TabButton>
      </div>
      {tab === 'local' && <LocalPanel />}
      {tab === 'url' && <UrlPanel />}
      {tab === 'import' && <ImportPanel />}
    </div>
  )
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 py-2 rounded text-sm font-medium ${
        active
          ? 'bg-indigo-600 text-white'
          : 'text-slate-300 hover:bg-slate-800'
      }`}
    >
      {children}
    </button>
  )
}

function LocalPanel() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [localPath, setLocalPath] = useState('')
  const [status, setStatus] = useState<UploadStatus>('idle')
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const navigate = useNavigate()

  async function uploadFileNow(f: File) {
    setStatus('uploading')
    setProgress(0)
    setError(null)
    try {
      const init = await api.initUpload({ filename: f.name, total_size: f.size })
      for (let i = 0; i < init.total_chunks; i++) {
        const start = i * init.chunk_size
        const end = Math.min(start + init.chunk_size, f.size)
        await withRetry(() => api.uploadChunk(init.upload_id, i, f.slice(start, end)), 5)
        setProgress((i + 1) / init.total_chunks)
      }
      setStatus('finalizing')
      const { video_id } = await api.finalizeUpload(init.upload_id)
      setStatus('done')
      navigate(`/frame/${video_id}`)
    } catch (e) {
      setStatus('error')
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function uploadFile() {
    if (!file) return
    await uploadFileNow(file)
  }

  function onDragOver(e: React.DragEvent) {
    // Must preventDefault on BOTH dragover and drop or the browser
    // opens the file in a new tab instead of firing our handler.
    e.preventDefault()
    if (!dragActive) setDragActive(true)
  }

  function onDragLeave(e: React.DragEvent) {
    // Only clear when the drag actually leaves the drop zone, not on
    // every child-element boundary crossing.
    if (e.currentTarget === e.target) setDragActive(false)
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragActive(false)
    const dropped = Array.from(e.dataTransfer.files || [])
    // Take the first video-like file. Some OSs report an empty type
    // for uncommon containers (mkv, etc.), so also accept anything
    // whose extension looks like a video.
    const f = dropped.find(
      (x) => x.type.startsWith('video/')
        || /\.(mp4|mkv|mov|webm|avi|m4v|wmv|flv)$/i.test(x.name),
    ) ?? dropped[0]
    if (!f) return
    setFile(f)
    // Auto-start — dropping IS the "go" signal.
    uploadFileNow(f)
  }

  async function usePath() {
    if (!localPath.trim()) return
    setStatus('finalizing')
    setError(null)
    try {
      const { video_id } = await api.uploadFromPath({ path: localPath.trim() })
      setStatus('done')
      navigate(`/frame/${video_id}`)
    } catch (e) {
      setStatus('error')
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const busy = status === 'uploading' || status === 'finalizing'
  return (
    <div
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className="relative"
    >
      <h2 className="text-lg mb-3">Upload from this device</h2>
      <div
        onClick={() => !busy && inputRef.current?.click()}
        className={`w-full mb-3 py-8 rounded-lg border-2 border-dashed text-center cursor-pointer transition-colors ${
          dragActive
            ? 'border-indigo-400 bg-indigo-500/10 text-indigo-200'
            : 'border-slate-700 bg-slate-900 text-slate-400 hover:border-slate-600'
        } ${busy ? 'opacity-60 pointer-events-none' : ''}`}
      >
        <p className="text-sm font-medium">
          {dragActive ? 'Release to upload' : 'Drop a video here or click to pick a file'}
        </p>
        <p className="text-xs mt-1 opacity-70">
          Upload starts immediately on drop
        </p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="video/*"
        disabled={busy}
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (!f) return
          setFile(f)
          uploadFileNow(f)
        }}
        className="hidden"
      />
      {file && (
        <p className="text-sm text-slate-400 mb-3">
          {file.name} — {fmtBytes(file.size)}
        </p>
      )}
      <button
        onClick={uploadFile}
        disabled={!file || busy}
        className="w-full py-3 rounded-lg bg-emerald-600 disabled:opacity-40 text-lg touch-manipulation"
      >
        {status === 'uploading' && `Uploading… ${Math.round(progress * 100)}%`}
        {status === 'finalizing' && 'Finalizing…'}
        {(status === 'idle' || status === 'done') && 'Start upload'}
        {status === 'error' && 'Retry'}
      </button>
      {status === 'uploading' && (
        <div className="mt-3 h-2 bg-slate-800 rounded">
          <div
            className="h-2 bg-indigo-500 rounded transition-all"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      )}

      {isLocalHost && (
        <div className="mt-6 pt-4 border-t border-slate-800">
          <label className="block text-sm text-slate-300 mb-1">
            ⚡ Or paste a local file path (desktop-only fast lane)
          </label>
          <p className="text-xs text-slate-500 mb-2">
            Skips the chunked upload — the backend copies the file directly.
            Works because the browser and backend share this machine's disk.
          </p>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder={`e.g. C:\\Users\\you\\Videos\\clip.mp4`}
              value={localPath}
              onChange={(e) => setLocalPath(e.target.value)}
              disabled={busy}
              className="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm font-mono"
            />
            <button
              onClick={usePath}
              disabled={!localPath.trim() || busy}
              className="px-4 rounded bg-indigo-600 disabled:opacity-40 text-sm"
            >
              Use path
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="mt-3 text-sm text-red-400 break-words">{error}</p>
      )}
    </div>
  )
}

function UrlPanel() {
  const [url, setUrl] = useState('')
  const [quality, setQuality] = useState<'1080p' | '720p' | '480p' | 'best'>('1080p')
  // 'paste' is a special sentinel: cookies_txt goes over the wire instead
  // of cookies_browser. Anything else names a browser to import from.
  const [cookies, setCookies] = useState<string>('')
  const [cookiesTxt, setCookiesTxt] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  async function submit() {
    if (!url.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      const usePaste = cookies === 'paste'
      const { video_id } = await api.uploadFromUrl({
        url: url.trim(),
        quality,
        cookies_browser: usePaste ? null : (cookies || null),
        cookies_txt: usePaste && cookiesTxt.trim() ? cookiesTxt : null,
      })
      // Video is queued — jump to the frame picker which handles the
      // download-in-progress state and switches to normal flow when ready.
      navigate(`/frame/${video_id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <h2 className="text-lg mb-3">Pull from a URL</h2>
      <p className="text-xs text-slate-500 mb-3">
        Powered by yt-dlp — works with 1000+ sites. Downloads happen one at
        a time on the backend; new URLs queue behind whatever's in flight.
      </p>

      <label className="block text-sm text-slate-300 mb-1">Video URL</label>
      <input
        type="url"
        placeholder="https://…"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        disabled={submitting}
        className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm mb-3"
      />

      <label className="block text-sm text-slate-300 mb-1">Quality</label>
      <select
        value={quality}
        onChange={(e) => setQuality(e.target.value as typeof quality)}
        disabled={submitting}
        className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm mb-3"
      >
        <option value="1080p">Best MP4 up to 1080p (default)</option>
        <option value="720p">Best MP4 up to 720p</option>
        <option value="480p">Best MP4 up to 480p</option>
        <option value="best">Best available (any format)</option>
      </select>

      <label className="block text-sm text-slate-300 mb-1">Cookies</label>
      <select
        value={cookies}
        onChange={(e) => setCookies(e.target.value)}
        disabled={submitting}
        className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm mb-1"
      >
        <option value="">None (public URLs only)</option>
        <option value="firefox">From Firefox</option>
        <option value="chrome">From Chrome</option>
        <option value="edge">From Edge</option>
        <option value="brave">From Brave</option>
        <option value="opera">From Opera</option>
        <option value="paste">Paste cookies.txt</option>
      </select>

      {cookies === '' && (
        <p className="text-xs text-slate-500 mb-4">
          Fine for public URLs. Members-only content needs cookies below.
        </p>
      )}
      {cookies && cookies !== 'paste' && cookies !== 'firefox' && (
        <p className="text-xs text-amber-400 mb-4">
          Chromium browsers (Chrome, Edge, Brave, Opera) on Windows may fail with
          <span className="font-mono"> "Failed to decrypt with DPAPI"</span> —
          Chromium 127+ locked cookies behind app-bound encryption. If you hit
          that, switch to <span className="font-mono">From Firefox</span> or
          <span className="font-mono"> Paste cookies.txt</span>.
        </p>
      )}
      {cookies === 'firefox' && (
        <p className="text-xs text-slate-500 mb-4">
          Uses cookies from Firefox on this machine.
        </p>
      )}
      {cookies === 'paste' && (
        <>
          <textarea
            value={cookiesTxt}
            onChange={(e) => setCookiesTxt(e.target.value)}
            disabled={submitting}
            placeholder="# Netscape HTTP Cookie File&#10;# https://curl.haxx.se/rfc/cookie_spec.html&#10;.example.com&#9;TRUE&#9;/&#9;TRUE&#9;1893456000&#9;session_id&#9;abc123..."
            rows={6}
            className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-xs font-mono mt-1 mb-2 resize-y"
          />
          <p className="text-xs text-slate-500 mb-4">
            Export via a browser extension like{' '}
            <span className="font-mono">Get cookies.txt LOCALLY</span> (Chrome/Edge)
            or <span className="font-mono">cookies.txt</span> (Firefox), then
            paste the file's contents here. The backend writes it to a
            temp file for yt-dlp and deletes it as soon as the download
            finishes (success or failure).
          </p>
        </>
      )}

      <button
        onClick={submit}
        disabled={!url.trim() || submitting}
        className="w-full py-3 rounded-lg bg-emerald-600 disabled:opacity-40 text-lg touch-manipulation"
      >
        {submitting ? 'Submitting…' : 'Fetch video'}
      </button>
      {error && <p className="mt-3 text-sm text-red-400 break-words">{error}</p>}
    </>
  )
}

async function withRetry<T>(fn: () => Promise<T>, attempts: number): Promise<T> {
  let lastErr: unknown
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn()
    } catch (e) {
      lastErr = e
      await new Promise((r) => setTimeout(r, 500 * (i + 1)))
    }
  }
  throw lastErr
}

function ImportPanel() {
  const [videoFile, setVideoFile] = useState<File | null>(null)
  const [funscriptFile, setFunscriptFile] = useState<File | null>(null)
  const [localPath, setLocalPath] = useState('')
  const [status, setStatus] = useState<UploadStatus | 'importing'>('idle')
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  async function readFunscript(): Promise<Array<{ at: number; pos: number }>> {
    if (!funscriptFile) throw new Error('pick a .funscript file first')
    const text = await funscriptFile.text()
    let parsed: { actions?: Array<{ at: number; pos: number }> }
    try {
      parsed = JSON.parse(text)
    } catch {
      throw new Error('funscript file is not valid JSON')
    }
    if (!Array.isArray(parsed.actions)) {
      throw new Error('funscript has no "actions" array')
    }
    return parsed.actions
  }

  async function submit() {
    setError(null)
    let actions: Array<{ at: number; pos: number }>
    try {
      actions = await readFunscript()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return
    }
    try {
      let videoId: string
      // Fast path when the frontend is served on localhost — the backend
      // just copies the file. Falls back to chunked upload otherwise.
      if (localPath.trim() && isLocalHost) {
        setStatus('finalizing')
        const res = await api.uploadFromPath({ path: localPath.trim() })
        videoId = res.video_id
      } else if (videoFile) {
        setStatus('uploading')
        setProgress(0)
        const init = await api.initUpload({
          filename: videoFile.name,
          total_size: videoFile.size,
        })
        for (let i = 0; i < init.total_chunks; i++) {
          const start = i * init.chunk_size
          const end = Math.min(start + init.chunk_size, videoFile.size)
          await withRetry(
            () => api.uploadChunk(init.upload_id, i, videoFile.slice(start, end)),
            5,
          )
          setProgress((i + 1) / init.total_chunks)
        }
        setStatus('finalizing')
        const fin = await api.finalizeUpload(init.upload_id)
        videoId = fin.video_id
      } else {
        setError('pick a video file (or paste a local path on desktop)')
        return
      }
      setStatus('importing')
      const res = await api.importFunscript(videoId, actions)
      setStatus('done')
      navigate(`/edit/${res.job_id}`)
    } catch (e) {
      setStatus('error')
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const busy = status === 'uploading' || status === 'finalizing' || status === 'importing'
  const canSubmit =
    !!funscriptFile && !busy && (!!videoFile || (isLocalHost && localPath.trim()))

  return (
    <>
      <h2 className="text-lg mb-3">Import an existing funscript</h2>
      <p className="text-xs text-slate-500 mb-3">
        Upload a video plus a matching <span className="font-mono">.funscript</span>{' '}
        file. The backend creates a completed job with your script as the output
        and drops you into the editor.
      </p>

      <label className="block text-sm text-slate-300 mb-1">Video</label>
      <input
        type="file"
        accept="video/*"
        disabled={busy}
        onChange={(e) => setVideoFile(e.target.files?.[0] ?? null)}
        className="w-full text-sm mb-3 file:mr-2 file:px-4 file:py-2 file:rounded file:border-0 file:bg-indigo-600 file:text-white"
      />
      {isLocalHost && (
        <>
          <p className="text-xs text-slate-500 mb-1">
            ⚡ Or paste a local path (desktop only, skips the upload):
          </p>
          <input
            type="text"
            placeholder={`e.g. C:\\Users\\you\\Videos\\clip.mp4`}
            value={localPath}
            onChange={(e) => setLocalPath(e.target.value)}
            disabled={busy}
            className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm font-mono mb-3"
          />
        </>
      )}

      <label className="block text-sm text-slate-300 mb-1">Funscript</label>
      <input
        type="file"
        accept=".funscript,.json,application/json"
        disabled={busy}
        onChange={(e) => setFunscriptFile(e.target.files?.[0] ?? null)}
        className="w-full text-sm mb-4 file:mr-2 file:px-4 file:py-2 file:rounded file:border-0 file:bg-indigo-600 file:text-white"
      />

      <button
        onClick={submit}
        disabled={!canSubmit}
        className="w-full py-3 rounded-lg bg-emerald-600 disabled:opacity-40 text-lg touch-manipulation"
      >
        {status === 'uploading' && `Uploading video… ${Math.round(progress * 100)}%`}
        {status === 'finalizing' && 'Finalizing…'}
        {status === 'importing' && 'Importing script…'}
        {(status === 'idle' || status === 'done') && 'Import + open editor'}
        {status === 'error' && 'Retry'}
      </button>
      {status === 'uploading' && (
        <div className="mt-3 h-2 bg-slate-800 rounded">
          <div
            className="h-2 bg-indigo-500 rounded transition-all"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      )}
      {error && <p className="mt-3 text-sm text-red-400 break-words">{error}</p>}
    </>
  )
}
