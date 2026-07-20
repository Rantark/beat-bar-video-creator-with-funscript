import json
import subprocess
from pathlib import Path
from typing import Any

from app.config import settings


def probe(video_path: Path) -> dict[str, Any]:
    """Return duration_ms, width, height, fps for a video via ffprobe."""
    cmd = [
        settings.ffprobe_path,
        "-v", "error",
        "-show_entries", "stream=width,height,r_frame_rate:format=duration",
        "-select_streams", "v:0",
        "-of", "json",
        str(video_path),
    ]
    out = subprocess.run(cmd, capture_output=True, check=True, text=True)
    data = json.loads(out.stdout)
    stream = data["streams"][0]
    duration_s = float(data["format"]["duration"])
    # r_frame_rate is a rational string like "30000/1001".
    num, den = stream["r_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) > 0 else 0.0
    return {
        "duration_ms": int(duration_s * 1000),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": fps,
    }


def generate_sprite(
    video_path: Path, out_sprite: Path, out_meta: Path, duration_ms: int
) -> dict[str, Any]:
    """Emit a tiled JPG sprite sheet plus a JSON metadata file.

    ffmpeg's `fps=1/N` means "one frame every N seconds"; `tile=CxR`
    packs them into a single JPG. We compute R from the actual thumb
    count so the sprite has no wasted cells beyond the last row.
    """
    interval_s = settings.sprite_interval_ms / 1000
    total_thumbs = max(1, int(duration_ms / 1000 / interval_s) + 1)
    cols = settings.sprite_cols
    rows = -(-total_thumbs // cols)  # ceil div

    out_sprite.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.ffmpeg_path,
        "-y",
        "-i", str(video_path),
        "-vf",
        f"fps=1/{interval_s},scale={settings.sprite_thumb_width}:"
        f"{settings.sprite_thumb_height},tile={cols}x{rows}",
        "-frames:v", "1",
        "-q:v", "4",
        str(out_sprite),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    meta = {
        "cols": cols,
        "rows": rows,
        "thumb_width": settings.sprite_thumb_width,
        "thumb_height": settings.sprite_thumb_height,
        "interval_ms": settings.sprite_interval_ms,
        "total_thumbs": total_thumbs,
    }
    out_meta.write_text(json.dumps(meta))
    return meta
