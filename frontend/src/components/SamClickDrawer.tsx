import { useRef, useState } from 'react'

/**
 * Click target picker for SAM 2 Object mode. The user scrubs the video
 * to a frame where the thing they want tracked is clearly visible,
 * then clicks it. SAM 2 propagates a mask of that specific object
 * across the whole clip. This component just captures the click and
 * shows a magenta target ring so the user can see what they picked.
 *
 * Emits normalized (0..1) coords in `onChange` — the container is
 * always the video's exact aspect ratio so the mapping is direct.
 */
export function SamClickDrawer({
  click,
  onChange,
  videoRef,
}: {
  click: { x: number; y: number } | null
  onChange: (
    click: { x: number; y: number },
    time_ms: number,
  ) => void
  videoRef: React.RefObject<HTMLVideoElement | null>
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [flashOn, setFlashOn] = useState(false)

  function pick(e: React.PointerEvent) {
    const el = boxRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const nx = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const ny = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
    const t = videoRef.current
    // Capture the current playback time so the backend knows which
    // frame the click applies to. SAM 2 propagates both forward and
    // backward from the prompt frame, so mid-clip prompts are fine.
    const time_ms = t ? Math.round(t.currentTime * 1000) : 0
    onChange({ x: nx, y: ny }, time_ms)
    setFlashOn(true)
    window.setTimeout(() => setFlashOn(false), 200)
  }

  return (
    <div
      ref={boxRef}
      onPointerDown={pick}
      className="absolute inset-0 cursor-crosshair select-none touch-none"
      title="Click the thing you want tracked"
    >
      {click && (
        <div
          className="absolute"
          style={{
            left: `${click.x * 100}%`,
            top: `${click.y * 100}%`,
            transform: 'translate(-50%, -50%)',
          }}
        >
          <div
            className={`w-8 h-8 rounded-full border-2 border-fuchsia-400 ${
              flashOn ? 'bg-fuchsia-400/40' : 'bg-fuchsia-500/10'
            }`}
          />
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-2 h-2 rounded-full bg-fuchsia-300" />
          </div>
        </div>
      )}
    </div>
  )
}
