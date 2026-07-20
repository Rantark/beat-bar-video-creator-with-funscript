from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("")
def list_videos():
    with get_db() as db:
        rows = db.execute("SELECT * FROM videos ORDER BY created_at DESC").fetchall()
    return [_video_dict(r) for r in rows]


@router.get("/{video_id}")
def get_video(video_id: str):
    with get_db() as db:
        row = db.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if not row:
        raise HTTPException(404, "video not found")
    return _video_dict(row)


@router.get("/{video_id}/sprite")
def get_sprite(video_id: str):
    path = settings.sprites_dir / f"{video_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "sprite not ready")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/{video_id}/stream")
def stream_video(video_id: str):
    with get_db() as db:
        row = db.execute(
            "SELECT path, filename FROM videos WHERE id=?", (video_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "video not found")
    path = Path(row["path"])
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    # Starlette's FileResponse honors HTTP Range, which is what mobile
    # <video> elements need for seeking without redownloading.
    return FileResponse(path, media_type="video/mp4")


@router.delete("/{video_id}")
def delete_video(video_id: str):
    with get_db() as db:
        row = db.execute("SELECT path FROM videos WHERE id=?", (video_id,)).fetchone()
        if not row:
            raise HTTPException(404, "video not found")
        db.execute("DELETE FROM jobs WHERE video_id=?", (video_id,))
        db.execute("DELETE FROM videos WHERE id=?", (video_id,))
    for p in (
        Path(row["path"]),
        settings.sprites_dir / f"{video_id}.jpg",
        settings.sprites_dir / f"{video_id}.json",
    ):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    return {"ok": True}


def _video_dict(row) -> dict:
    # Row access via string key is safe here because the schema declares
    # every field we read; older DBs get the missing columns via the
    # startup migration in db.py.
    def get(k, default=None):
        try:
            return row[k]
        except (IndexError, KeyError):
            return default

    return {
        "id": row["id"],
        "filename": row["filename"],
        "size_bytes": row["size_bytes"],
        "duration_ms": row["duration_ms"],
        "width": row["width"],
        "height": row["height"],
        "fps": row["fps"],
        "sprite_ready": bool(row["sprite_ready"]),
        "sprite_cols": row["sprite_cols"],
        "sprite_rows": row["sprite_rows"],
        "sprite_interval_ms": row["sprite_interval_ms"],
        "sprite_thumb_width": row["sprite_thumb_width"],
        "sprite_thumb_height": row["sprite_thumb_height"],
        "created_at": row["created_at"],
        "source_type": get("source_type", "upload"),
        "source_url": get("source_url"),
        "download_status": get("download_status"),
        "download_progress": get("download_progress", 0.0) or 0.0,
        "download_error": get("download_error"),
    }
