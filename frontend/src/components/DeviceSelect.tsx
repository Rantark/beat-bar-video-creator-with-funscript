import { useEffect, useState } from 'react'
import { api } from '../api'
import type { DeviceChoice, DeviceState } from '../types'

/**
 * CPU / GPU picker for neural detection modes (audio BEAT This!, pose
 * YOLOv8). Fetches the backend's device snapshot once on mount so the
 * dropdown can show the GPU name (or a hint that CUDA torch isn't
 * installed) without the user having to guess.
 *
 * Meaningful only when the caller's mode actually uses neural
 * inference. For audio mode the parent should hide it when the neural
 * tracker toggle is off.
 */
export function DeviceSelect({
  value,
  onChange,
}: {
  value: DeviceChoice
  onChange: (v: DeviceChoice) => void
}) {
  const [state, setState] = useState<DeviceState | null>(null)

  useEffect(() => {
    let cancelled = false
    api.deviceState()
      .then((s) => { if (!cancelled) setState(s) })
      .catch(() => { /* silent — non-critical */ })
    return () => { cancelled = true }
  }, [])

  const cudaAvailable = state?.cuda_available ?? false
  const gpuName = state?.gpu_name

  return (
    <div className="mt-3">
      <div className="flex items-center gap-3">
        <label className="text-xs text-slate-400 shrink-0">Compute device</label>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value as DeviceChoice)}
          className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm"
        >
          <option value="auto">Auto — use GPU if available, else CPU</option>
          <option value="cpu">CPU (safe, always works)</option>
          <option value="cuda">
            GPU (CUDA){cudaAvailable && gpuName ? ` — ${gpuName}` : ''}
          </option>
        </select>
      </div>
      {state && !cudaAvailable && (
        <p className="mt-1 text-xs text-amber-300">
          CUDA not detected in this backend's PyTorch build.{' '}
          <span className="text-slate-400">
            Selecting GPU will silently fall back to CPU. To enable GPU
            inference, reinstall PyTorch with CUDA support in the
            backend venv (see README).
          </span>
        </p>
      )}
      {state && cudaAvailable && (
        <p className="mt-1 text-xs text-slate-500">
          Choose CPU if you're actively gaming — GPU inference will
          share compute with your game and can drop framerate 10-30%.
        </p>
      )}
    </div>
  )
}
