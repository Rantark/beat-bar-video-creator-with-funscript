"""yt-dlp based URL video ingest with a single-slot queue.

Downloads serialize on a module-level lock so bandwidth isn't split
across multiple pulls. CV processing runs independently in its own
BackgroundTasks so a slow download never blocks a running job.
"""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

from app.config import settings
from app.db import get_db

# One in-flight download at a time. A queued BackgroundTask blocks on
# acquire — cheap because they're independent threads.
_download_lock = threading.Lock()

# yt-dlp format specifiers. `<=?` is a *conditional* height filter that
# still matches formats where `height` is missing from the info dict —
# many progressive-MP4 sites (Rule34Video, most tube sites, etc.) don't
# populate that field so a hard `<=N` filter rejects everything.
# We used to require ext=mp4 too, but merge_output_format='mp4' remuxes
# non-MP4 sources cleanly, so no need for the extra constraint.
FORMAT_PRESETS = {
    "1080p": "best[height<=?1080]/bv*[height<=?1080]+ba/best",
    "720p":  "best[height<=?720]/bv*[height<=?720]+ba/best",
    "480p":  "best[height<=?480]/bv*[height<=?480]+ba/best",
    "best":  "bv*+ba/b",
}


def download_video(
    video_id: str,
    url: str,
    quality: str = "1080p",
    cookies_browser: str | None = None,
    cookies_txt: str | None = None,
) -> None:
    """BackgroundTask entry point. Runs the whole download + probe +
    sprite generation flow so /api/videos/{id} reflects a ready video
    when finished."""
    try:
        with _download_lock:
            _set_status(video_id, "downloading", 0.0)
            _run(video_id, url, quality, cookies_browser, cookies_txt)
    except Exception as e:  # pragma: no cover — surface to the user
        _set_status(video_id, "failed", 0.0, error=_format_error(e))


def _format_error(exc: Exception) -> str:
    """Compact error string: exception summary first (never truncated),
    then the TAIL of the traceback (where the actual failure lives).
    Fixed a prior bug where truncating format_exc from the head kept
    the outer stack frames and dropped the exception message."""
    summary = f"{type(exc).__name__}: {exc}".strip() or type(exc).__name__
    tb = traceback.format_exc()
    max_len = 2000
    body_room = max_len - len(summary) - 4
    if body_room <= 0 or len(tb) <= body_room:
        return f"{summary}\n\n{tb}"
    # Keep the tail — the exception + last few frames matter most.
    return f"{summary}\n\n…\n{tb[-body_room:]}"


def _run(
    video_id: str, url: str, quality: str,
    cookies_browser: str | None, cookies_txt: str | None,
) -> None:
    # Late import so a broken yt-dlp install doesn't block the whole app
    # from starting — only URL ingest breaks.
    import yt_dlp

    fmt = FORMAT_PRESETS.get(quality, FORMAT_PRESETS["1080p"])

    def progress_hook(d: dict) -> None:
        if d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        got = d.get("downloaded_bytes", 0)
        if total > 0:
            _set_status(video_id, "downloading", max(0.0, min(0.99, got / total)))

    # %(ext)s lets yt-dlp pick the right extension; we look up the actual
    # produced filename after the fact.
    outtmpl = str(settings.uploads_dir / f"{video_id}.%(ext)s")
    ydl_opts: dict = {
        "format": fmt,
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    # cookies_txt wins if both are provided: it's the explicit workaround
    # for Chromium 127+ where cookies-from-browser hits the app-bound
    # encryption / DPAPI wall (yt-dlp issue 10927).
    cookies_tmpfile: Path | None = None
    if cookies_txt:
        settings.uploads_tmp_dir.mkdir(parents=True, exist_ok=True)
        cookies_tmpfile = settings.uploads_tmp_dir / f"{video_id}.cookies.txt"
        cookies_tmpfile.write_text(cookies_txt, encoding="utf-8")
        ydl_opts["cookiefile"] = str(cookies_tmpfile)
    elif cookies_browser:
        ydl_opts["cookiesfrombrowser"] = (cookies_browser,)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            try:
                declared_path = Path(ydl.prepare_filename(info))
            except Exception:
                declared_path = None
    finally:
        # Session tokens in cookies.txt are sensitive — delete no matter
        # how the download finished.
        if cookies_tmpfile is not None:
            try:
                cookies_tmpfile.unlink(missing_ok=True)
            except OSError:
                pass

    actual = _resolve_output(video_id, declared_path)
    if actual is None:
        raise RuntimeError("yt-dlp did not produce an output file")

    # Probe + sprite gen mirror the chunked-upload finalize path exactly.
    from app.routes.uploads import _build_sprite_task  # local import avoids a cycle
    from app.thumbnails import probe

    info_dict = probe(actual)
    filename = info.get("title") or actual.name
    with get_db() as db:
        db.execute(
            "UPDATE videos SET filename=?, path=?, size_bytes=?, "
            "duration_ms=?, width=?, height=?, fps=?, "
            "download_status='ready', download_progress=1.0 WHERE id=?",
            (
                filename[:255],
                str(actual),
                actual.stat().st_size,
                info_dict["duration_ms"],
                info_dict["width"],
                info_dict["height"],
                info_dict["fps"],
                video_id,
            ),
        )
    _build_sprite_task(video_id)


def _resolve_output(video_id: str, declared: Path | None) -> Path | None:
    """After merge, the real file may have a different extension than
    declared. Fall back to the first matching file in uploads_dir."""
    if declared and declared.exists():
        return declared
    candidates = sorted(
        settings.uploads_dir.glob(f"{video_id}.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _set_status(
    video_id: str, status: str, progress: float, error: str | None = None,
) -> None:
    with get_db() as db:
        db.execute(
            "UPDATE videos SET download_status=?, download_progress=?, "
            "download_error=? WHERE id=?",
            (status, progress, error, video_id),
        )
