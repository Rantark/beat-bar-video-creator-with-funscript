# funscript-gen — self-hosted mobile-first funscript generator with a built-in editor and audio-driven mode

I built a small self-hosted web app that generates `.funscript` files
from videos. It runs locally on a Windows desktop and is driven from a
phone browser over Tailscale, or as a native desktop app in its own
window. Nothing leaves your machine.

## What it does

Upload a video from your phone (or paste a URL — it uses yt-dlp), tell
the app what to track, and it produces a funscript. There's an
in-browser editor for tweaking the result. Everything is designed to
work on a small phone screen and expands cleanly on desktop.

Four detection modes cover different content types:

- **Zone** — pyramidal Lucas-Kanade optical flow inside a rectangle you
  draw. Best when a single element moves rhythmically in a well-defined
  area.
- **Line** — a finite-length line segment placed anywhere on the frame;
  each background-subtraction contour that crosses it becomes one
  stroke event.
- **Marker** — a small circular hit point for rhythm-game content. Uses
  inner-vs-outer color contrast, HSV distance, and optionally a
  captured template image so it survives translucent overlays over
  animated backgrounds.
- **Audio** — spectral-flux onset detection on the video's audio track.
  For content where the rhythm is carried by the music instead of a
  visible marker.

## The audio mode is the new headline

The audio pipeline turns a music-driven video into a funscript without
needing anything on-screen to track. It's the part I spent the most
recent work on:

- Onset detection with adjustable sensitivity, min gap, and a frequency
  band (kicks below 200 Hz, snares 200–8k, voice-heavy 100–500 Hz).
- **Section regularization** — the timeline is split into 5-second-step
  windows between a user-set min and max length (default 10–30 s) with
  a fluctuation knob that varies section length randomly around a
  target. Each section detects its own dominant beat period and emits a
  clean grid at that tempo, phase-aligned to the first real onset.
  Truly silent sections drop out and the idle animation fills them.
- **Beat-pattern variety** — per-section chance to shift to half-time
  or double-time subdivisions, so a song with a steady tempo still
  yields visibly different rhythms per section.
- **Preset beat patterns** — build a library of on/off patterns (rows
  of 4–16 checkboxes). The algorithm picks one per section, weighted so
  fast sections favor dense patterns and slow sections favor sparse
  ones. Each pattern's row shows a slow / medium / fast label based on
  its density.
- **Rhythm-game beat-bar overlay** — the debug MP4 draws a scrolling
  bar along the bottom of the video with a fixed hit marker; beats
  slide right-to-left and cross the marker at exactly their onset time.
  Upload your own bar background, hit marker sprite, and beat sprite
  (transparent PNGs composite cleanly) to match a specific game's look.

The onset list is deterministic, so re-runs on the same audio produce
the same section layout and pattern picks — you can tune other knobs
without the underlying grid shuffling under you.

## Editor

The editor is where you spend most of your time on real content.
Auto-generated funscripts get you 80% of the way; the editor covers
the last 20%.

- SVG timeline with tap-to-select, drag-to-move, rubber-band
  multi-select, quick-select for peaks / troughs / all, and a nudge pad
  with ±1 / ±5 / ±10 / ±100 buttons.
- Manual pos / time number inputs when a single point is selected.
- 200-step undo history; save-with-original-snapshot; one-click reset.
- Frame step (`,` / `.`, Shift = ×10) and playback speed 0.25× to 2×.
- **A/B loop playback** — set A (`I`), set B (`O`), toggle (`L`), clear
  (`U`). Loops that section on repeat while you tune.
- **Fill range** — replace everything between A and B with a flat hold,
  a steady beat at chosen BPM/min/max positions, or a linear ramp. One
  click to scrub the algorithmic jumble out of sections where no beat
  bar was actually visible.
- **Sections panel** (audio mode) — vertical amber dividers on the
  timeline plus a button list below. Click §N to jump to section N and
  set A/B loop to it. Each row shows the period + which pattern was
  used, and offers **→ pat N** buttons that replace that section's
  beats with a pattern from the library at the section's own tempo.
- **Rebuild beat-bar video** — after editing sections, regenerate the
  overlay MP4 so it matches. Runs in the background with live progress.

## Other niceties

- **Chunked upload** with per-chunk linear-backoff retry — phone
  hotspot uploads survive brief drops.
- **URL ingest** via yt-dlp. Choose a quality preset, optionally point
  it at a browser profile for cookies (Chromium 127+'s app-bound
  encryption is broken with yt-dlp, so there's also a paste-your-own-
  cookies.txt path).
- **Local path fast-lane** — point it at a file already on the same
  machine and skip the upload entirely.
- **Sprite-sheet timeline scrubber** — server generates a JPG sprite
  once, phone scrubs a long video without ever touching the video
  decoder.
- **Zoom loupe** on touch for pixel-accurate marker placement; hides
  on mouse because you don't need magnification with a cursor.
- **Per-speed stroke shaping** — max_up / max_up_fast /
  max_down_fast / max_down. Fast beat sections aren't forced into
  full-swing strokes; slow beats still get full amplitude.
- **Saved tuning presets** per detection mode — save a set of knobs by
  name and apply it to any video.
- **Import funscript** — bring an existing funscript alongside a video
  to jump straight to the editor.
- **Per-job delete** to reclaim disk space.
- **Desktop app** — same web app in a native window (WebView2 on
  Windows via PyWebView). Backend still binds `0.0.0.0` so the phone
  keeps working over Tailscale.
- **Full keyboard shortcut layer** for desktop editing.

## Tech notes

- **Backend**: Python 3.14, FastAPI, SQLite (WAL), OpenCV 5 (headless),
  NumPy, SciPy, ffmpeg 8 as an external binary. Jobs run in FastAPI
  `BackgroundTasks`. Audio onset detection is pure SciPy STFT + adaptive
  baseline — no librosa dependency.
- **Frontend**: React 19, Vite 6, TypeScript, Tailwind v4,
  react-router-dom.
- **Networking**: Vite dev server proxies `/api` to FastAPI in dev; the
  desktop bundle serves the built frontend from FastAPI directly at
  `:8000`. Both dev and prod bind `0.0.0.0` so the phone works over
  Tailscale.
- **Storage**: Everything under `backend/storage/` — uploads, sprites,
  output funscripts + debug MP4s + section metadata, SQLite database.
  Delete the folder to reset.

## Requirements

- Windows 10/11, Python 3.14, Node 24 LTS, ffmpeg 8.x
- Tailscale (for phone access — optional if desktop-only)

## Install (short version)

```powershell
# 1. Extract funscript-gen.zip to any path (examples use C:\Projects\funscript-gen)

# 2. Backend
cd C:\Projects\funscript-gen\backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Frontend
cd ..\frontend
npm install
npm approve-scripts esbuild
npm rebuild esbuild

# 4. Launch — pick one:
cd ..
start.bat            # dev mode, two terminals, http://localhost:5173/
start-desktop.bat    # native window, http://localhost:8000/ inside
```

Full install + tuning docs and per-detection-mode notes live in the
`README.md` and `docs/` folder inside the archive.

## Not in scope

- Multi-user / auth. Single-user by design; Tailscale gates access.
- Cloud deployment. It's built for a home desktop.

Happy to answer questions or take feedback. The code is deliberately
small and organized so a specific algorithm change (swap
Lucas-Kanade for something else in zone mode, or replace the onset
detector) is one file.
