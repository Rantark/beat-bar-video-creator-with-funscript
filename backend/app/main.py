from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routes import jobs, presets, uploads, videos


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (
        settings.uploads_dir,
        settings.uploads_tmp_dir,
        settings.sprites_dir,
        settings.output_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title="funscript-gen", lifespan=lifespan)

# Vite proxies /api → 8000 in dev, so CORS isn't strictly needed there.
# Enabled anyway in case we ever hit the API directly from the phone.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(uploads.router)
app.include_router(videos.router)
app.include_router(jobs.router)
app.include_router(presets.router)

# Serve the built frontend when it exists (desktop-app / prod bundle
# path). In dev the Vite server handles this, so if frontend/dist is
# absent we just skip the mount and /api keeps working.
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # SPA fallback — serves an actual file at that path if it exists
    # (favicon, robots, etc.), otherwise returns index.html so React
    # Router owns the client-side routes. Registered after every /api
    # router above, so API routes win the match.
    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path:
            candidate = (FRONTEND_DIST / full_path).resolve()
            # Reject anything that resolves outside the dist tree.
            if FRONTEND_DIST.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
