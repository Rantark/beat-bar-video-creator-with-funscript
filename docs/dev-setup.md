# dev-setup — first-time install

You only run this once per machine. Daily-use commands live in [run.md](run.md).

## Prerequisites

Install these before continuing. Every command in this doc assumes they're on
`PATH` in whichever terminal you're using.

| Tool          | Version tested | Where I put it                    |
|---------------|----------------|-----------------------------------|
| Python        | 3.14           | (installer default)               |
| Node          | 24 LTS         | `C:\Program Files\nodejs\`        |
| ffmpeg        | 8.1            | `C:\ffmpeg\bin\ffmpeg.exe` (with `ffprobe.exe` next to it) |
| git           | any            | (installer default)               |

Verify:

```powershell
python --version
node --version
& C:\ffmpeg\bin\ffmpeg.exe -version | Select-Object -First 1
```

If Node isn't on `PATH` in a fresh terminal, add it once:

```powershell
[Environment]::SetEnvironmentVariable(
  'Path', $env:Path + ';C:\Program Files\nodejs', 'User')
```

Restart the terminal after running that.

## Get the code

Extract `funscript-gen.zip` to your chosen location. The examples below
assume `C:\Projects\funscript-gen`; any path works as long as you're
consistent.

```powershell
cd C:\Projects\funscript-gen
```

## Backend

```powershell
cd C:\Projects\funscript-gen\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

The install pulls FastAPI, uvicorn, pydantic, pydantic-settings, python-multipart
for the API, and OpenCV (headless) + NumPy + SciPy for the motion-detection
processors.

## Frontend

```powershell
cd C:\Projects\funscript-gen\frontend
npm install
```

npm 11+ requires explicit approval for install scripts. `esbuild`'s postinstall
(which fetches its platform binary) is needed for Vite to build. If your
`package.json` doesn't already include an `allowScripts` block for it:

```powershell
npm approve-scripts esbuild
npm rebuild esbuild
```

After that the approval persists in `package.json` — leave it there.

## Configuration (`.env`)

```powershell
Copy-Item C:\Projects\funscript-gen\backend\.env.example `
          C:\Projects\funscript-gen\backend\.env
```

Edit `backend\.env` if you want to change defaults — the file lists every
tunable knob with a one-line explanation.

> **BOM caveat.** Do **not** edit `.env` with Windows PowerShell 5.1's
> `Set-Content -Encoding utf8` or with Notepad's "Save As UTF-8" — both write a
> BOM at the start of the file that used to silently make the first line's
> variable disappear. The backend now strips BOM defensively
> (`utf-8-sig`), but the cleanest habit is to edit `.env` in VS Code / Notepad++
> / any modern editor, which default to BOM-less UTF-8.

## Sanity check

Backend imports and lifespan work:

```powershell
cd C:\Projects\funscript-gen\backend
.\.venv\Scripts\python.exe -c "from app.main import app; print('backend imports OK')"
```

Frontend typechecks:

```powershell
cd C:\Projects\funscript-gen\frontend
npx tsc -b --noEmit
```

Then jump to [run.md](run.md) to start both.

## Tuning knobs (recap)

Set any of these in `backend\.env`; the backend picks them up on next start.
Effects are covered in the main [README](../README.md#tuning-knobs).

- `SMOOTHING_WINDOW`, `SMOOTHING_POLYORDER` — Savitzky-Golay filter shape.
- `PEAK_PROMINENCE` — how confident a peak has to be to become an action.
- `PEAK_MIN_DISTANCE_MS` — minimum spacing between actions (applies to zone
  peaks/troughs and line crossings alike).
- `UPLOAD_CHUNK_SIZE` — bytes per upload chunk.
- `FFMPEG_PATH` — change if you moved ffmpeg.
