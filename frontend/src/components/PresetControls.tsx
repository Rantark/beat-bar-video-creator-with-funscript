import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Preset } from '../types'

/**
 * Save / load / delete tuning profiles per mode. Presets store only
 * the tuning fields (declared in `PRESET_KEYS` on the caller side),
 * not spatial placement — so a preset works across any video.
 */
export function PresetControls({
  mode,
  currentParams,
  onLoad,
}: {
  mode: 'marker' | 'line'
  currentParams: Record<string, unknown>
  onLoad: (params: Record<string, unknown>) => void
}) {
  const [presets, setPresets] = useState<Preset[]>([])
  const [selectedId, setSelectedId] = useState<string>('')
  const [busy, setBusy] = useState(false)

  async function reload() {
    try {
      setPresets(await api.listPresets(mode))
    } catch { /* silent — no preset flow is optional */ }
  }
  useEffect(() => { reload() }, [mode])

  async function save() {
    const name = window.prompt('Preset name?')?.trim()
    if (!name) return
    setBusy(true)
    try {
      const created = await api.createPreset({ name, mode, params: currentParams })
      await reload()
      setSelectedId(created.id)
    } finally {
      setBusy(false)
    }
  }

  async function overwrite() {
    if (!selectedId) return
    const current = presets.find(p => p.id === selectedId)
    if (!current) return
    if (!window.confirm(`Overwrite preset "${current.name}" with current tuning?`)) return
    setBusy(true)
    try {
      await api.updatePreset(selectedId, { params: currentParams })
      await reload()
    } finally {
      setBusy(false)
    }
  }

  async function del() {
    if (!selectedId) return
    const current = presets.find(p => p.id === selectedId)
    if (!current) return
    if (!window.confirm(`Delete preset "${current.name}"?`)) return
    setBusy(true)
    try {
      await api.deletePreset(selectedId)
      setSelectedId('')
      await reload()
    } finally {
      setBusy(false)
    }
  }

  function onPick(id: string) {
    setSelectedId(id)
    if (!id) return
    const p = presets.find(pr => pr.id === id)
    if (p) onLoad(p.params)
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
      <span className="text-slate-500 shrink-0">Preset</span>
      <select
        value={selectedId}
        onChange={(e) => onPick(e.target.value)}
        disabled={busy}
        className="flex-1 min-w-32 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm"
      >
        <option value="">— select —</option>
        {presets.map(p => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>
      <button
        onClick={save}
        disabled={busy}
        className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-xs"
        title="Save the current tuning as a new preset"
      >
        Save as…
      </button>
      <button
        onClick={overwrite}
        disabled={busy || !selectedId}
        className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40 text-xs"
        title="Overwrite the selected preset with current tuning"
      >
        Overwrite
      </button>
      <button
        onClick={del}
        disabled={busy || !selectedId}
        className="px-2 py-1 rounded bg-red-900/70 hover:bg-red-900 disabled:opacity-40 text-xs"
        title="Delete the selected preset"
      >
        Delete
      </button>
    </div>
  )
}
