# tailscale — access it from your phone

Assumes Tailscale is already installed and signed into the same tailnet on both
your desktop and your phone.

## The one-line summary

Vite is already bound to `0.0.0.0`, so once Windows Firewall lets connections in
on port 5173, browse to `http://<desktop-tailscale-ip>:5173/` on your phone.
That's it — the phone only ever hits port 5173. Vite's dev proxy forwards
`/api/*` to `localhost:8000` on the *desktop*, so port 8000 doesn't need to
cross the network at all.

## Steps

### 1. Find the desktop's Tailscale IP

```powershell
tailscale ip -4
```

You'll get something like `100.x.y.z`. Write it down — that's what your phone
uses.

### 2. Start both servers with `0.0.0.0` binding

The commands in [run.md](run.md) already do this:

```powershell
# backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# frontend
npm run dev            # vite.config.ts sets host: '0.0.0.0'
```

(You only actually need port 5173 reachable from the phone — see the summary
above — but binding uvicorn to `0.0.0.0` too makes it possible to hit the API
directly from the phone for debugging.)

### 3. Allow inbound on Windows Firewall

Windows treats the Tailscale interface as a network like any other. By default
inbound to a random high port is blocked. Add a rule once:

```powershell
# Run from an elevated PowerShell.
New-NetFirewallRule -DisplayName "funscript-gen (Vite dev)" `
  -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow -Profile Any
# Optional — only needed if you want to hit the FastAPI docs from the phone.
New-NetFirewallRule -DisplayName "funscript-gen (FastAPI)" `
  -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any
```

To remove them later: `Remove-NetFirewallRule -DisplayName "funscript-gen*"`.

### 4. On the phone

Browse to:

```
http://100.x.y.z:5173/
```

(with the IP from step 1). The React app loads, `/api` calls proxy through Vite
to FastAPI, uploads chunk over Tailscale, and everything just works.

## Sanity checks

**Can the phone reach the desktop at all?** In the Tailscale mobile app, hit
"Ping" against the desktop machine name. If that fails, this doc is not your
problem — Tailscale is.

**Can the phone reach port 5173 specifically?** From the phone browser:
`http://100.x.y.z:5173/` should load. If it hangs or refuses, the firewall
rule from step 3 isn't in place (or wasn't run elevated).

**Does the API work through the proxy?** From the phone browser:
`http://100.x.y.z:5173/api/health` should return `{"status":"ok"}`. If the page
loads but the API call fails, Vite is up but the backend isn't running.

## Notes

- **This exposes an unauthenticated app.** Tailscale is the only thing between
  the internet and your funscript-gen. If your tailnet only contains devices
  you own, that's fine — that's the whole point of this design. Don't run this
  on a shared tailnet.
- **Uploads over cellular hotspot are the intended use.** Chunk size defaults
  to 2 MiB and each chunk retries with linear backoff up to 5 times, so brief
  connection drops don't kill the whole upload.
- **If Vite ever won't accept a phone connection** even with the firewall rule
  in place, check the `server.host` setting in `frontend/vite.config.ts` — it
  must be `'0.0.0.0'` (or unset with `--host 0.0.0.0` on the command line).
  Running `npm run dev` in this repo picks up the config, no extra flags needed.
