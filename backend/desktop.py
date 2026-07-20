"""Desktop-app launcher.

Runs the same FastAPI backend as `uvicorn app.main:app`, but in a
background thread, then opens a native webview window pointed at it.

The backend still binds 0.0.0.0:8000, so a phone on the same Tailscale
network can reach it exactly like the two-window dev setup. This just
gives the desktop side a native window instead of a browser tab.

Requires:
  - `pywebview` installed in the venv
  - The frontend built into ../frontend/dist (npm run build)
"""

import threading
import time
import urllib.error
import urllib.request

import uvicorn
import webview

from app.main import app

HOST = "0.0.0.0"
PORT = 8000
WINDOW_URL = f"http://127.0.0.1:{PORT}/"


def run_backend() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def wait_for_backend(timeout_s: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{PORT}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.15)
    return False


def main() -> None:
    threading.Thread(target=run_backend, daemon=True).start()
    if not wait_for_backend():
        raise RuntimeError(f"Backend did not become ready on port {PORT}")
    webview.create_window(
        "funscript-gen",
        WINDOW_URL,
        width=1400,
        height=900,
        resizable=True,
        min_size=(900, 600),
    )
    webview.start()


if __name__ == "__main__":
    main()
