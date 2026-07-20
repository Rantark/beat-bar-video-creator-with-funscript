import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.config import settings
from app.db import get_db
from app.thumbnails import generate_sprite, probe

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chunk_path(upload_id: str, index: int) -> Path:
    return settings.uploads_tmp_dir / upload_id / f"chunk-{index:06d}"


@router.post("/init")
def init_upload(payload: dict):
    filename = payload.get("filename")
    total_size = int(payload.get("total_size", 0))
    if not filename or total_size <= 0:
        raise HTTPException(400, "filename and total_size required")
    chunk_size = int(payload.get("chunk_size") or settings.upload_chunk_size)
    total_chunks = -(-total_size // chunk_size)  # ceil div

    upload_id = str(uuid.uuid4())
    (settings.uploads_tmp_dir / upload_id).mkdir(parents=True, exist_ok=True)

    with get_db() as db:
        db.execute(
            "INSERT INTO uploads(id,filename,total_size,chunk_size,total_chunks,"
            "received_chunks,created_at) VALUES(?,?,?,?,?,?,?)",
            (upload_id, filename, total_size, chunk_size, total_chunks, "[]", _now_iso()),
        )
    return {
        "upload_id": upload_id,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "received_chunks": [],
    }


@router.get("/{upload_id}")
def get_upload(upload_id: str):
    with get_db() as db:
        row = db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
    if not row:
        raise HTTPException(404, "unknown upload")
    return {
        "upload_id": row["id"],
        "filename": row["filename"],
        "total_size": row["total_size"],
        "chunk_size": row["chunk_size"],
        "total_chunks": row["total_chunks"],
        "received_chunks": json.loads(row["received_chunks"]),
        "video_id": row["video_id"],
    }


@router.put("/{upload_id}/chunks/{index}")
async def upload_chunk(upload_id: str, index: int, request: Request):
    # Read the raw body BEFORE opening the sqlite connection — the body
    # read is the slow bit and we don't want it holding a write lock.
    data = await request.body()
    with get_db() as db:
        row = db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
        if not row:
            raise HTTPException(404, "unknown upload")
        if index < 0 or index >= row["total_chunks"]:
            raise HTTPException(400, "chunk index out of range")

        _chunk_path(upload_id, index).write_bytes(data)
        received = sorted(set(json.loads(row["received_chunks"])) | {index})
        db.execute(
            "UPDATE uploads SET received_chunks=? WHERE id=?",
            (json.dumps(received), upload_id),
        )
    return {"received": received}


@router.post("/{upload_id}/finalize")
def finalize_upload(upload_id: str, background_tasks: BackgroundTasks):
    with get_db() as db:
        row = db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
        if not row:
            raise HTTPException(404, "unknown upload")
        received = set(json.loads(row["received_chunks"]))
        expected = set(range(row["total_chunks"]))
        missing = sorted(expected - received)
        if missing:
            raise HTTPException(
                400,
                f"missing chunks: {missing[:10]}"
                f"{'... (+' + str(len(missing) - 10) + ')' if len(missing) > 10 else ''}",
            )

        video_id = str(uuid.uuid4())
        ext = Path(row["filename"]).suffix or ".mp4"
        final_path = settings.uploads_dir / f"{video_id}{ext}"

        with final_path.open("wb") as fout:
            for i in range(row["total_chunks"]):
                fout.write(_chunk_path(upload_id, i).read_bytes())

        chunk_dir = settings.uploads_tmp_dir / upload_id
        for p in chunk_dir.iterdir():
            p.unlink()
        chunk_dir.rmdir()

        info = probe(final_path)
        db.execute(
            "INSERT INTO videos(id,filename,path,size_bytes,duration_ms,width,height,fps,"
            "sprite_ready,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (video_id, row["filename"], str(final_path), row["total_size"],
             info["duration_ms"], info["width"], info["height"], info["fps"],
             0, _now_iso()),
        )
        db.execute("UPDATE uploads SET video_id=? WHERE id=?", (video_id, upload_id))

    # Sprite generation runs after the response is sent — the client
    # polls GET /api/videos/{id} for sprite_ready before rendering the picker.
    background_tasks.add_task(_build_sprite_task, video_id)
    return {"video_id": video_id}


@router.post("/from-url")
def upload_from_url(payload: dict, background_tasks: BackgroundTasks):
    """Kick off a yt-dlp download. Returns immediately with a video_id
    the client can poll via GET /api/videos/{id} — the row's
    download_status transitions queued → downloading → ready (or failed)
    and sprite_ready flips true when the post-download sprite gen finishes."""
    url = (payload.get("url") or "").strip()
    quality = payload.get("quality", "1080p")
    cookies_browser = payload.get("cookies_browser") or None
    cookies_txt = payload.get("cookies_txt") or None
    if not url:
        raise HTTPException(400, "url required")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url must be http(s)")
    if quality not in ("1080p", "720p", "480p", "best"):
        raise HTTPException(400, "unknown quality preset")
    if cookies_browser and cookies_browser not in (
        "chrome", "firefox", "edge", "brave", "opera", "safari", "chromium",
    ):
        raise HTTPException(400, "unknown cookies_browser")
    if cookies_txt and not isinstance(cookies_txt, str):
        raise HTTPException(400, "cookies_txt must be a string")

    video_id = str(uuid.uuid4())
    now = _now_iso()
    # Placeholder row — path is empty and gets filled by the downloader
    # when the file lands. filename is the URL until we learn a real title.
    with get_db() as db:
        db.execute(
            "INSERT INTO videos(id, filename, path, size_bytes, "
            "source_type, source_url, download_status, download_progress, "
            "sprite_ready, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (video_id, url[:255], "", 0, "url", url, "queued", 0.0, 0, now),
        )
    from app.processing.downloader import download_video
    background_tasks.add_task(
        download_video, video_id, url, quality, cookies_browser, cookies_txt,
    )
    return {"video_id": video_id}


@router.post("/from-path")
def upload_from_path(payload: dict, background_tasks: BackgroundTasks):
    """Copy a local file into storage/uploads and register it as a video.
    Faster than chunked upload on the desktop where the browser and
    backend share the filesystem. Client is responsible for gating this
    to localhost — it works from anywhere the backend can reach the path."""
    raw = (payload.get("path") or "").strip()
    if not raw:
        raise HTTPException(400, "path required")
    src = Path(raw)
    if not src.is_file():
        raise HTTPException(400, f"not a file: {raw}")

    video_id = str(uuid.uuid4())
    ext = src.suffix or ".mp4"
    dst = settings.uploads_dir / f"{video_id}{ext}"
    shutil.copy2(src, dst)

    info = probe(dst)
    now = _now_iso()
    with get_db() as db:
        db.execute(
            "INSERT INTO videos(id, filename, path, size_bytes, duration_ms, "
            "width, height, fps, source_type, sprite_ready, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (video_id, src.name, str(dst), dst.stat().st_size,
             info["duration_ms"], info["width"], info["height"], info["fps"],
             "upload", 0, now),
        )
    background_tasks.add_task(_build_sprite_task, video_id)
    return {"video_id": video_id}


def _build_sprite_task(video_id: str) -> None:
    with get_db() as db:
        row = db.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if not row:
        return
    sprite_path = settings.sprites_dir / f"{video_id}.jpg"
    meta_path = settings.sprites_dir / f"{video_id}.json"
    meta = generate_sprite(Path(row["path"]), sprite_path, meta_path, row["duration_ms"])
    with get_db() as db:
        db.execute(
            "UPDATE videos SET sprite_ready=1, sprite_cols=?, sprite_rows=?, "
            "sprite_interval_ms=?, sprite_thumb_width=?, sprite_thumb_height=? "
            "WHERE id=?",
            (meta["cols"], meta["rows"], meta["interval_ms"],
             meta["thumb_width"], meta["thumb_height"], video_id),
        )
