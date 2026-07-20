# funscript-gen

Self-hosted, mobile-first web app that generates `.funscript` files from
videos. Runs locally on a Windows desktop; drive it from a phone browser
over Tailscale, or launch it as a desktop app in its own window. Nothing
leaves your machine.

## What it does

You give it a video and pick a detection strategy. It produces a
funscript, optionally with an annotated MP4 you can play in any video
player. An in-browser editor covers the last-mile fixes.

**Four detection modes**

- **Zone** — Lucas-Kanade optical flow inside a rectangle you draw. Best
  when a single element moves rhythmically in a well-defined area.
- **Line** — a horizontal or vertical line segment. Each crossing
  becomes a stroke event.
- **Marker** — a small circular hit point for rhythm-game overlays. Uses
  inner-vs-outer color contrast, HSV distance, and (optionally) a
  captured template image so it works on translucent markers over
  animated backgrounds.
- **Audio** — spectral-flux onset detection on the video's audio track.
  Regularized into 5–60 s sections of stable tempo, with a fully
  configurable rhythm-game-style visual bar rendered onto the debug MP4
  (custom sprites for the bar background, hit marker, and beat).

**Editor**

OFS-style SVG timeline with multi-select, rubber-band, nudge pad, manual
pos/time inputs, frame stepping, playback speed, A/B loop playback, fill
a range with a pattern, per-section beat replacement (audio mode), 200-
step undo, reset-to-original snapshot, and a full keyboard layer.

**Extras**

- Chunked upload with per-chunk retry so phone-hotspot uploads survive
  drops
- URL ingest via yt-dlp (paste a page URL, choose quality, optional
  browser-cookies or pasted `cookies.txt` for gated sites)
- Local path fast-lane for videos already on the same machine
- Sprite-sheet timeline scrubber — the phone scrubs a 4-hour video
  without ever touching the video decoder
- Saved tuning presets per detection mode
- Per-job delete to reclaim space; import an existing funscript
  alongside a video to jump straight to the editor
- Desktop launcher — same app in a native window (WebView2 on Windows,
  no browser chrome), while the backend keeps serving the phone over
  Tailscale exactly like the dev setup

## Requirements

| Tool     | Version tested | Notes                                          |
|----------|----------------|------------------------------------------------|
| Windows  | 10 / 11        | Cross-platform-friendly, but the launcher scripts and PATH advice assume Windows. |
| Python   | 3.14           | Must be on `PATH`.                             |
| Node.js  | 24 LTS         | Must be on `PATH`.                             |
| ffmpeg   | 8.x            | Default install location `C:\ffmpeg\bin\ffmpeg.exe` (with `ffprobe.exe` next to it). Override via `FFMPEG_PATH` in `.env`. |

## Installation

```powershell
# 1. Extract funscript-gen.zip anywhere. Examples use C:\Projects\funscript-gen.
cd C:\Projects\funscript-gen

# 2. Backend — Python venv + pip requirements
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Frontend — npm dependencies + esbuild approval
cd ..\frontend
npm install
npm approve-scripts esbuild
npm rebuild esbuild

# 4. Configuration (optional — defaults are sensible)
cd ..
Copy-Item backend\.env.example backend\.env
# Edit backend\.env only to override defaults (e.g. non-standard ffmpeg
# location or tuned processor knobs).
```

**Notes**
- If Node isn't on `PATH` in a fresh terminal:
  ```powershell
  [Environment]::SetEnvironmentVariable('Path', $env:Path + ';C:\Program Files\nodejs', 'User')
  ```
  Then restart the terminal.
- Don't edit `.env` with Notepad or PowerShell 5.1's `Set-Content -Encoding utf8` — both write a UTF-8 BOM. The backend strips it defensively but VS Code / Notepad++ is cleaner.

## Running

**Dev mode (hot reload):**
```powershell
start.bat
```
Opens two terminals — backend on `:8000`, frontend on `:5173`. Close
either or run `stop.bat` to shut down.

**Desktop app (native window):**
```powershell
start-desktop.bat
```
First run builds the frontend into `frontend/dist` and installs
`pywebview`. Subsequent runs launch immediately. Everything is served
from a single port (`:8000`), backend still binds `0.0.0.0` so the phone
keeps working.

**Manual — two terminals:**
```powershell
# Terminal 1 (backend)
cd C:\Projects\funscript-gen\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2 (frontend, dev only)
cd C:\Projects\funscript-gen\frontend
npm run dev
```

**Phone access** — open `http://<tailscale-ip>:5173/` (dev) or
`http://<tailscale-ip>:8000/` (desktop / built). See
[docs/tailscale.md](docs/tailscale.md) for the one-time Windows firewall
rule.

## Getting started

1. **Upload** a video (drag-drop, phone camera roll, paste URL, or local
   path).
2. **Wait** for the sprite sheet — a few seconds for short clips.
3. **Pick a detection mode** from the frame picker:
   - **Zone** — touch-and-drag a rectangle. Optional invert flip.
   - **Line** — pick orientation + center + length; only crossings
     inside the highlighted strip count.
   - **Marker** — tap the hit point. Zoom loupe helps place it
     pixel-perfect on touch. Optionally capture a template image from
     the current frame — the backend runs `cv2.matchTemplate` alongside
     the color signals and beats become much more reliable.
   - **Audio** — configure sensitivity + frequency band. Optional
     rhythm-game overlay with your own bar / hit / beat sprites. Add a
     library of on/off patterns; the algorithm picks one per section
     weighted by section speed (fast sections → dense patterns, slow
     sections → sparse ones). Section length min/target/max in
     5-second steps with a fluctuation knob.
4. **Render beat-bar video** (auto-on in Audio mode; a plain "Render
   debug video" checkbox in the other modes) writes an annotated MP4
   next to the funscript.
5. **Generate** — the job runs in the background; Jobs tab shows
   progress. When done, download the funscript or open in the editor.

## Editor

- SVG timeline; tap to select, drag to move, rubber-band multi-select,
  quick-select "peaks / troughs / all".
- Nudge pad ±1 / ±5 / ±10 / ±100 or arrow-key equivalents.
- **A/B loop** — set A (I key) and B (O) from the current time, toggle
  (L), clear (U). Playback snaps back to A when it crosses B.
- **Fill range** — replace everything between A and B with a flat hold,
  a steady beat at chosen BPM/min/max, or a linear ramp.
- **Sections** (audio mode) — vertical amber dividers on the timeline
  and a button list below. Click §N to jump + set A/B to that section.
  Per-section **→ pat N** buttons replace that section's beats with a
  pattern from the library, applied at the section's own tempo.
- **Rebuild beat-bar video** — after editing sections, regenerate the
  overlay MP4 to match. Runs in the background with live progress.
- Frame step (`,` / `.`, Shift = ×10), speed 0.25×–2× (`1`–`4`), mute
  (`M`), zoom (`+` / `-` or Ctrl+wheel), Ctrl+S save, Ctrl+Z undo (200
  steps), Ctrl+A select all.

## Documentation

More detailed docs under `docs/`:
- [dev-setup.md](docs/dev-setup.md) — first-time install, tuning recap
- [run.md](docs/run.md) — daily commands, storage layout, common ops
- [tailscale.md](docs/tailscale.md) — phone access over Tailscale

## Tuning knobs (backend/.env — restart backend after editing)

| Var                       | Default | Effect                                                             |
|---------------------------|---------|--------------------------------------------------------------------|
| `SMOOTHING_WINDOW`        | 11      | Savitzky-Golay window (odd). Higher = smoother zone output.        |
| `SMOOTHING_POLYORDER`     | 3       | SG polynomial order. Must be `< SMOOTHING_WINDOW`.                 |
| `PEAK_PROMINENCE`         | 4.0     | Higher = fewer, more confident stroke events (zone mode).          |
| `PEAK_MIN_DISTANCE_MS`    | 80      | Minimum ms between actions (zone + line).                          |
| `ZONE_ROLLING_WINDOW_MS`  | 3000    | Local auto-range window in zone mode.                              |
| `ZONE_MIN_AMPLITUDE_PX`   | 5.0     | Floor on local range; prevents amplifying LK noise.                |
| `MARKER_PROMINENCE`       | 15.0    | Marker-mode peak prominence, 0-100 scale.                          |
| `MARKER_MIN_DISTANCE_MS`  | 100     | Minimum ms between marker beats.                                   |
| `MARKER_CONTRAST_WEIGHT`  | 1.0     | Weight of spatial contrast (primary marker signal).                |
| `MARKER_DELTA_WEIGHT`     | 0.5     | Weight of temporal delta (fallback for solid backgrounds).         |
| `MARKER_HUE_WEIGHT`       | 0.5     | HSV hue-distance component.                                        |
| `MARKER_SAT_WEIGHT`       | 0.5     | HSV saturation-distance component.                                 |
| `MARKER_TEMPLATE_WEIGHT`  | 1.5     | Weight of template-matching score when template is uploaded.       |
| `MARKER_FAST_INTERVAL_MS` | 250     | Interval threshold below which strokes are fully "fast."           |
| `MARKER_SLOW_INTERVAL_MS` | 1000    | Interval threshold above which strokes are fully "slow."           |
| `MARKER_IDLE_ENABLED`     | true    | Slow oscillation in silent gaps between sections.                  |
| `UPLOAD_CHUNK_SIZE`       | 2 MiB   | Bytes per upload chunk (`.env` uses `2097152`).                    |
| `FFMPEG_PATH`             | `C:\ffmpeg\bin\ffmpeg.exe` | `ffprobe.exe` assumed next to it.                |

Audio-mode knobs (sensitivity, section length, patterns, sprites) are
per-job and set in the UI rather than the env file.

## Layout

```
funscript-gen/
├── start.bat              Dev launcher (backend + Vite in two terminals)
├── start-desktop.bat      Native-window launcher (WebView2)
├── stop.bat               Stops ports 5173 / 8000
├── backend/
│   ├── app/
│   │   ├── main.py        FastAPI app + static-serve for built frontend
│   │   ├── config.py      Settings (env-tunable)
│   │   ├── db.py          SQLite schema + get_db()
│   │   ├── thumbnails.py  ffprobe + ffmpeg sprite generation
│   │   ├── routes/        upload, videos, jobs, presets
│   │   └── processing/    zone, line, marker, audio, beat_actions,
│   │                      audio_beats, images, debug, funscript,
│   │                      downloader
│   ├── desktop.py         PyWebView launcher entry point
│   ├── storage/           uploads, sprites, output, app.db
│   ├── requirements.txt
│   ├── pyproject.toml
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.tsx        Shell + responsive nav
│   │   ├── api.ts         Typed client
│   │   ├── pages/         Home, Upload, FramePicker, Jobs, Editor
│   │   └── components/    SpriteScrubber, Zone/Line/MarkerDrawer,
│   │                      TimelineGraph, StrokerVisualizer, PresetControls,
│   │                      BeatShapeControls, BeatPatternEditor, SpriteUpload
│   ├── vite.config.ts
│   └── package.json
└── docs/
```

## Security — read before deploying

This app is **not designed to be exposed to the public internet**.

- **No authentication.** Anyone who can reach the port controls
  everything: upload/download videos, generate/edit funscripts, delete
  files.
- **CORS is open** (`allow_origins=["*"]`). Any origin can hit the API
  from a browser.
- **Binds `0.0.0.0`** so Tailscale/LAN peers can reach it. There is no
  IP allow-list.
- **`POST /api/uploads/from-path`** copies **any file the backend
  process can read** into storage, based on a client-supplied path.
  Reachable → readable. This is a convenience path for a local desktop
  and is not sandboxed. Consider removing it if the app is reachable
  from anywhere you don't fully control.
- **`POST /api/uploads/from-url`** feeds a URL to `yt-dlp`; safe-ish
  because yt-dlp gates the request, but it is still a network side
  channel that runs on your machine.

Safe deployment models this was built for:

- Localhost-only (`start-desktop.bat` — native window, no network needed).
- A private Tailscale tailnet, with the Windows firewall closed to
  everything else.
- A LAN you fully trust, with no port forwarding.

Not recommended: reverse-proxying it to the public internet, exposing
it on a cloud VM without a WireGuard/Tailscale gate, or running it on
a network with untrusted devices.

## Notes

Single-user by design — Tailscale gates access, no auth in the app. If
you expose it beyond a private tailnet that's on you.
