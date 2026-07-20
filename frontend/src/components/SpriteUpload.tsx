import { useRef } from 'react'

/**
 * One image slot for a rhythm-game sprite (bar background / hit marker /
 * beat). Files are read as base64 data URLs so they travel with the
 * job params — no separate upload endpoint needed. Backend decodes via
 * `app.processing.images.decode_data_url`.
 */
export function SpriteUpload({
  label,
  hint,
  value,
  onChange,
}: {
  label: string
  hint: string
  value: string | null
  onChange: (data: string | null) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)

  function pick() { inputRef.current?.click() }

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    // Cap at ~2 MB so a stray 4K PNG doesn't blow up the JSON payload.
    if (f.size > 2 * 1024 * 1024) {
      alert('Image too large — please pick something under 2 MB.')
      e.target.value = ''
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result
      if (typeof result === 'string') onChange(result)
    }
    reader.readAsDataURL(f)
    // Reset so re-picking the same file re-triggers onChange.
    e.target.value = ''
  }

  return (
    <div className="flex items-center gap-3">
      <div className="w-16 h-16 shrink-0 border border-slate-700 rounded bg-black bg-[url('data:image/svg+xml;utf8,<svg%20xmlns=%22http://www.w3.org/2000/svg%22%20width=%2216%22%20height=%2216%22><rect%20width=%228%22%20height=%228%22%20fill=%22%23222%22/><rect%20x=%228%22%20y=%228%22%20width=%228%22%20height=%228%22%20fill=%22%23222%22/></svg>')] bg-[length:16px_16px]">
        {value && (
          <img
            src={value}
            alt={label}
            className="w-full h-full object-contain"
          />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-slate-300">{label}</p>
        <p className="text-xs text-slate-500 leading-tight">{hint}</p>
      </div>
      <div className="flex flex-col gap-1 shrink-0">
        <button
          onClick={pick}
          className="px-2 py-1 rounded text-xs bg-slate-700 hover:bg-slate-600"
        >
          {value ? 'Replace' : 'Upload'}
        </button>
        {value && (
          <button
            onClick={() => onChange(null)}
            className="px-2 py-1 rounded text-xs bg-slate-800 hover:bg-slate-700 text-slate-400"
          >
            Clear
          </button>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        onChange={onFile}
        className="hidden"
      />
    </div>
  )
}
