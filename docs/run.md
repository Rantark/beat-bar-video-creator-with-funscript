# run — daily commands

Two terminals, one for each server. Both stay running while you use the app.

## Terminal 1 — backend

```powershell
cd C:\Projects\funscript-gen\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0` binds to every interface so Tailscale can reach it. On a
  laptop, this includes the local Wi-Fi — fine on your home network, but if you
  ever plug into an untrusted network, restart with `--host 127.0.0.1`.
- Serves the API at `http://localhost:8000/api/*` and interactive docs at
  `http://localhost:8000/docs`.
- On start it creates any missing `storage/` subdirectories and runs
  `PRAGMA journal_mode=WAL` on the SQLite file if needed.

Add `--reload` while you're editing backend code — it restarts on any file
change under `app/`.

## Terminal 2 — frontend

```powershell
cd C:\Projects\funscript-gen\frontend
npm run dev
```

- Serves the React app at `http://localhost:5173/`.
- Vite is already configured to bind `0.0.0.0`, so the phone can reach it via
  Tailscale (see [tailscale.md](tailscale.md)).
- Vite proxies `/api/*` to `http://localhost:8000`, so the client is
  origin-agnostic — the same URLs work in dev and in production.

## From the browser

- Desktop: `http://localhost:5173/`.
- Phone (over Tailscale): `http://<desktop-tailscale-ip>:5173/`.

## Stopping

`Ctrl-C` in each terminal. If a terminal is closed without stopping, ports
5173 and 8000 stay held until the process is killed:

```powershell
Get-NetTCPConnection -LocalPort 5173,8000 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

## Where files live

Everything the app persists sits under `backend\storage\`:

```
backend\storage\
├── app.db              SQLite database (WAL mode)
├── uploads\            Finalized videos, named <video_id>.<ext>
│   └── .tmp\           In-progress upload chunks; deleted after finalize
├── sprites\            <video_id>.jpg (sprite sheet) + <video_id>.json (meta)
└── output\             <job_id>.funscript
```

## Common operations

**Delete a video** — hit the "Delete" button on the Videos tab (front-end).
Cascades to any jobs for that video and removes the source + sprite files.

**Re-run a video** with a different zone/line — Jobs tab → "Re-run" jumps back
to the frame picker for that video, no re-upload needed.

**Tune peak detection without a code edit** — edit `backend\.env`, restart the
backend terminal. New jobs pick up the new values; already-finished funscripts
aren't retroactively re-run.

**Reset everything** — stop the backend, then:

```powershell
Remove-Item -Recurse -Force C:\Projects\funscript-gen\backend\storage
```

The lifespan handler will recreate the layout on next start.

## Optional: build once, serve from one process

If you'd rather not run two terminals daily (e.g. for a long unattended
session), build the frontend to static files:

```powershell
cd C:\Projects\funscript-gen\frontend
npm run build
```

That produces `frontend\dist\`. You can then mount it in FastAPI —
serving assets from the same port as the API removes the need for the Vite
proxy. Not wired up yet in this pass; a two-line addition to `app/main.py`
when you want it.
