# Security

**This app is not designed for public internet exposure.** It has no
authentication and no rate limiting. Read this before deploying.

## Threat model

funscript-gen is built for a single user running it on their own
desktop, reachable from their own devices over LAN or a private
Tailscale tailnet. It is safe when:

- Only bound to `localhost` (the desktop launcher does this in effect —
  the WebView2 window talks to `127.0.0.1:8000`, and while the backend
  still listens on `0.0.0.0`, your firewall determines who else can
  reach it).
- Bound to `0.0.0.0` behind a Tailscale-only or LAN-only firewall rule.
- Running on a LAN with only trusted devices.

It is **not** safe to:

- Reverse-proxy to the public internet.
- Run on a cloud VM without a WireGuard / Tailscale gate.
- Expose on a shared/hotel/office Wi-Fi.

## Known behaviors

Anyone who can reach the port has full control of the app. That
includes:

- **No authentication.** Every endpoint is unauthenticated.
- **CORS is fully open** (`allow_origins=["*"]`) so any origin can call
  the API from a browser.
- **Local file access via `POST /api/uploads/from-path`.** Accepts an
  arbitrary filesystem path from the client and copies that file into
  storage. The endpoint is a convenience for the localhost desktop
  workflow and is not sandboxed — a reachable API means the process's
  read access to your filesystem is reachable too. Remove or gate this
  endpoint if the app is reachable from anywhere you don't fully
  control.
- **URL ingest via `POST /api/uploads/from-url`.** Feeds URLs to
  `yt-dlp`. yt-dlp itself gates the request, but it is a network side
  channel that runs on your machine.
- **Bind address is `0.0.0.0`** by default so Tailscale/LAN peers can
  reach it. There is no built-in IP allow-list.

## Reporting a vulnerability

Open a GitHub issue with `[security]` in the title, or a private
security advisory via GitHub's security tab on the repo. Please don't
include details of an unpatched issue in a public issue if it would
expose users who've already deployed the app.
