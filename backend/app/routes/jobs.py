import json
import shutil
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app.config import settings
from app.db import get_db
from app.processing.audio import AudioProcessor
from app.processing.base import VideoInfo
from app.processing.funscript import write_funscript
from app.processing.line import LineProcessor
from app.processing.marker import MarkerProcessor
from app.processing.zone import ZoneProcessor

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("")
def create_job(payload: dict, background_tasks: BackgroundTasks):
    video_id = payload.get("video_id")
    mode = payload.get("mode")
    params = payload.get("params") or {}
    if mode not in ("zone", "line", "marker", "audio"):
        raise HTTPException(400, "mode must be 'zone', 'line', 'marker', or 'audio'")
    if not video_id:
        raise HTTPException(400, "video_id required")

    with get_db() as db:
        v = db.execute("SELECT id FROM videos WHERE id=?", (video_id,)).fetchone()
        if not v:
            raise HTTPException(404, "video not found")
        job_id = str(uuid.uuid4())
        now = _now_iso()
        db.execute(
            "INSERT INTO jobs(id,video_id,mode,params_json,status,progress,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (job_id, video_id, mode, json.dumps(params), "queued", 0.0, now, now),
        )
    background_tasks.add_task(_run_job, job_id)
    return {"job_id": job_id}


@router.get("")
def list_jobs():
    with get_db() as db:
        rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [_job_dict(r) for r in rows]


@router.get("/{job_id}")
def get_job(job_id: str):
    with get_db() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "job not found")
    return _job_dict(row)


@router.get("/{job_id}/meta")
def get_job_meta(job_id: str):
    """Mode-specific auxiliary metadata (audio jobs currently — section
    boundaries + pattern library). 404 if the job didn't produce meta."""
    with get_db() as db:
        row = db.execute(
            "SELECT output_path FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    if not row or not row["output_path"]:
        raise HTTPException(404, "job not found or no output")
    meta_path = Path(row["output_path"]).with_suffix(".meta.json")
    if not meta_path.exists():
        raise HTTPException(404, "no meta for this job")
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(500, "meta file unreadable")


@router.get("/{job_id}/debug")
def download_debug(job_id: str):
    """Annotated MP4 with overlays + audio-synced event flashes."""
    path = settings.output_dir / f"{job_id}_debug.mp4"
    if not path.exists():
        raise HTTPException(404, "debug render not available for this job")
    with get_db() as db:
        row = db.execute("SELECT video_id FROM jobs WHERE id=?", (job_id,)).fetchone()
        v = (
            db.execute("SELECT filename FROM videos WHERE id=?", (row["video_id"],)).fetchone()
            if row else None
        )
    # Match source video name so all three files (video/funscript/debug)
    # group together alphabetically in the user's file browser.
    dl_name = (Path(v["filename"]).stem + "_debug.mp4") if v else path.name
    return FileResponse(path, media_type="video/mp4", filename=dl_name)


@router.put("/{job_id}/funscript")
def update_funscript(job_id: str, payload: dict):
    """Overwrite the funscript with edited actions. On first save the
    original is snapshotted so /reset can restore it."""
    with get_db() as db:
        row = db.execute(
            "SELECT output_path FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    if not row or not row["output_path"]:
        raise HTTPException(404, "job not found or no output")
    path = Path(row["output_path"])
    if not path.exists():
        raise HTTPException(404, "funscript missing on disk")

    actions = payload.get("actions")
    if not isinstance(actions, list):
        raise HTTPException(400, "actions must be a list")
    # Validate each action — enforcing types here spares the writer from
    # a per-action assert that would surface as a 500.
    cleaned: list[dict] = []
    for i, a in enumerate(actions):
        if not isinstance(a, dict):
            raise HTTPException(400, f"action {i}: not an object")
        try:
            at_ms = int(a["at"])
            pos = int(a["pos"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, f"action {i}: missing/invalid at or pos")
        if at_ms < 0:
            raise HTTPException(400, f"action {i}: negative at")
        pos = max(0, min(100, pos))
        cleaned.append({"at": at_ms, "pos": pos})
    # Ensure strictly increasing timestamps so downstream players don't
    # trip on out-of-order entries the user may have accidentally created
    # by dragging one point past another.
    cleaned.sort(key=lambda a: a["at"])
    deduped: list[dict] = []
    for a in cleaned:
        if deduped and a["at"] <= deduped[-1]["at"]:
            a["at"] = deduped[-1]["at"] + 1
        deduped.append(a)

    original = _original_path_of(path)
    if not original.exists():
        shutil.copy2(path, original)

    write_funscript(path, deduped)
    return {"ok": True, "action_count": len(deduped), "has_original": True}


@router.delete("/{job_id}")
def delete_job(job_id: str):
    """Remove a job and everything it produced from disk. Source video
    is preserved — delete that separately from the Videos page if you
    want to reclaim its space too."""
    with get_db() as db:
        row = db.execute(
            "SELECT output_path FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "job not found")
        db.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    # Clean up produced files. Debug MP4 and original snapshot are
    # optional, so use missing_ok — no fuss if they were never rendered.
    removed = []
    if row["output_path"]:
        fs_path = Path(row["output_path"])
        try:
            fs_path.unlink(missing_ok=True)
            removed.append("funscript")
        except OSError:
            pass
        orig = _original_path_of(fs_path)
        try:
            orig.unlink(missing_ok=True)
            if orig != fs_path:
                removed.append("original")
        except OSError:
            pass
        meta = fs_path.with_suffix(".meta.json")
        try:
            if meta.exists():
                meta.unlink()
                removed.append("meta")
        except OSError:
            pass
    debug_path = settings.output_dir / f"{job_id}_debug.mp4"
    try:
        if debug_path.exists():
            debug_path.unlink()
            removed.append("debug_mp4")
    except OSError:
        pass
    return {"ok": True, "removed": removed}


@router.post("/{job_id}/rerender-debug")
def rerender_debug(job_id: str, background_tasks: BackgroundTasks):
    """Rebuild the beat-bar overlay MP4 from the current funscript so
    it matches edits made in the editor. Runs in the background — poll
    /jobs/{id} for status; when done, /jobs/{id}/debug returns the new
    render. Only meaningful for audio-mode jobs (they're the only ones
    that carry the pattern/sprite params required to draw the bar).
    """
    with get_db() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "job not found")
    if row["mode"] != "audio":
        raise HTTPException(400, "rerender only supported for audio jobs")
    if row["status"] != "done" or not row["output_path"]:
        raise HTTPException(400, "job not done")
    background_tasks.add_task(_rerender_audio_debug, job_id)
    return {"ok": True}


def _rerender_audio_debug(job_id: str) -> None:
    """Background worker for POST /jobs/{id}/rerender-debug."""
    try:
        with get_db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return
            video_row = db.execute(
                "SELECT * FROM videos WHERE id=?", (row["video_id"],)
            ).fetchone()
            if not video_row:
                _fail(job_id, "video row missing")
                return
            db.execute(
                "UPDATE jobs SET status=?, progress=?, updated_at=? WHERE id=?",
                ("processing", 0.0, _now_iso(), job_id),
            )

        params = json.loads(row["params_json"])
        audio_params = params.get("audio") or {}
        fs_path = Path(row["output_path"])
        fs_data = json.loads(fs_path.read_text(encoding="utf-8"))
        actions_list = fs_data.get("actions") or []
        # Beats = action timestamps at (or very close to) the trough.
        # Editor-time reshaping means we can't just replay the original
        # beat list — pull them off the current funscript instead so the
        # rendered bar matches what the toy will actually do.
        beat_times = sorted({
            int(a["at"]) for a in actions_list
            if isinstance(a, dict) and int(a.get("pos", 100)) <= 5
        })

        from app.processing.debug import render_audio_debug
        from app.processing.images import decode_data_url
        import numpy as np

        bar_img = decode_data_url(audio_params.get("bar_image"), with_alpha=False)
        hit_img = decode_data_url(audio_params.get("hit_image"), with_alpha=True)
        beat_img = decode_data_url(audio_params.get("beat_image"), with_alpha=True)
        lookahead_ms = max(200, int(audio_params.get("lookahead_ms", 1500)))
        fps = float(video_row["fps"]) if video_row["fps"] else 30.0
        beat_frames = [int(round(t / 1000.0 * fps)) for t in beat_times]
        debug_out = settings.output_dir / f"{job_id}_debug.mp4"

        def on_progress(p: float) -> None:
            with get_db() as db:
                db.execute(
                    "UPDATE jobs SET progress=?, updated_at=? WHERE id=?",
                    (max(0.0, min(1.0, p)), _now_iso(), job_id),
                )

        render_audio_debug(
            source_video=Path(video_row["path"]),
            out_path=debug_out,
            beat_frame_indices=beat_frames,
            beat_times_ms=beat_times,
            video_duration_ms=int(video_row["duration_ms"]),
            novelty=np.zeros(0, dtype=np.float32),
            novelty_hop_ms=10.0,
            bar_image=bar_img,
            hit_image=hit_img,
            beat_image=beat_img,
            lookahead_ms=lookahead_ms,
            progress_cb=on_progress,
        )
        with get_db() as db:
            db.execute(
                "UPDATE jobs SET status=?, progress=?, updated_at=? WHERE id=?",
                ("done", 1.0, _now_iso(), job_id),
            )
    except Exception:
        _fail(job_id, traceback.format_exc())


@router.post("/{job_id}/funscript/reset")
def reset_funscript(job_id: str):
    """Restore the funscript from the snapshotted original."""
    with get_db() as db:
        row = db.execute(
            "SELECT output_path FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    if not row or not row["output_path"]:
        raise HTTPException(404, "job not found or no output")
    path = Path(row["output_path"])
    original = _original_path_of(path)
    if not original.exists():
        raise HTTPException(404, "no original snapshot exists")
    shutil.copy2(original, path)
    return {"ok": True}


@router.get("/{job_id}/download")
def download_job(job_id: str):
    with get_db() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        v = (
            db.execute("SELECT filename FROM videos WHERE id=?", (row["video_id"],)).fetchone()
            if row else None
        )
    if not row:
        raise HTTPException(404, "job not found")
    if row["status"] != "done" or not row["output_path"]:
        raise HTTPException(400, "job not done")
    path = Path(row["output_path"])
    if not path.exists():
        raise HTTPException(404, "output missing")
    # Nice download name — source stem + .funscript.
    dl_name = (Path(v["filename"]).stem + ".funscript") if v else path.name
    return FileResponse(path, media_type="application/json", filename=dl_name)


def _job_dict(row) -> dict:
    debug_exists = (settings.output_dir / f"{row['id']}_debug.mp4").exists()
    out_path = row["output_path"]
    has_original = (
        bool(out_path) and _original_path_of(Path(out_path)).exists()
    )
    return {
        "id": row["id"],
        "video_id": row["video_id"],
        "mode": row["mode"],
        "params": json.loads(row["params_json"]),
        "status": row["status"],
        "progress": row["progress"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "debug_available": debug_exists,
        "has_original": has_original,
    }


def _original_path_of(funscript_path: Path) -> Path:
    """Companion path for the pre-edit backup. Uses .original.funscript so
    it sits right next to the live file in the storage listing."""
    return funscript_path.with_name(funscript_path.stem + ".original.funscript")


def _run_job(job_id: str) -> None:
    """Background: mark processing, run processor, mark done/failed."""
    try:
        with get_db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return
            video = db.execute(
                "SELECT * FROM videos WHERE id=?", (row["video_id"],)
            ).fetchone()
            if not video:
                _fail(job_id, "video row missing")
                return
            db.execute(
                "UPDATE jobs SET status=?, updated_at=? WHERE id=?",
                ("processing", _now_iso(), job_id),
            )

        info = VideoInfo(
            id=video["id"], path=Path(video["path"]),
            duration_ms=video["duration_ms"], width=video["width"],
            height=video["height"], fps=video["fps"],
        )
        params = json.loads(row["params_json"])
        out_path = settings.output_dir / f"{job_id}.funscript"
        debug_out_path: Path | None = None
        if bool(params.get("debug")):
            debug_out_path = settings.output_dir / f"{job_id}_debug.mp4"

        def on_progress(p: float) -> None:
            with get_db() as db:
                db.execute(
                    "UPDATE jobs SET progress=?, updated_at=? WHERE id=?",
                    (max(0.0, min(1.0, p)), _now_iso(), job_id),
                )

        _pick_processor(row["mode"]).run(
            info, params, out_path, on_progress, debug_out_path=debug_out_path,
        )

        with get_db() as db:
            db.execute(
                "UPDATE jobs SET status=?, progress=?, output_path=?, updated_at=? "
                "WHERE id=?",
                ("done", 1.0, str(out_path), _now_iso(), job_id),
            )
    except Exception:
        _fail(job_id, traceback.format_exc())


def _fail(job_id: str, error: str) -> None:
    with get_db() as db:
        db.execute(
            "UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?",
            ("failed", error, _now_iso(), job_id),
        )


def _pick_processor(mode: str):
    if mode == "zone":
        return ZoneProcessor()
    if mode == "line":
        return LineProcessor()
    if mode == "marker":
        return MarkerProcessor()
    if mode == "audio":
        return AudioProcessor()
    raise ValueError(f"unknown mode: {mode}")


@router.post("/import")
def import_funscript_as_job(payload: dict):
    """Create a completed job from an externally-supplied funscript so
    the user can jump straight to the editor. Also snapshots the file
    as .original.funscript so Reset works out of the box."""
    video_id = payload.get("video_id")
    actions = payload.get("actions")
    if not video_id:
        raise HTTPException(400, "video_id required")
    if not isinstance(actions, list):
        raise HTTPException(400, "actions must be a list")

    with get_db() as db:
        v = db.execute("SELECT id FROM videos WHERE id=?", (video_id,)).fetchone()
        if not v:
            raise HTTPException(404, "video not found")

    # Validate + normalize.
    cleaned: list[dict] = []
    for i, a in enumerate(actions):
        if not isinstance(a, dict):
            raise HTTPException(400, f"action {i}: not an object")
        try:
            at_ms = int(a["at"])
            pos = int(a["pos"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, f"action {i}: missing/invalid at or pos")
        if at_ms < 0:
            raise HTTPException(400, f"action {i}: negative at")
        cleaned.append({"at": at_ms, "pos": max(0, min(100, pos))})
    cleaned.sort(key=lambda a: a["at"])
    # Strictly-increasing timestamps.
    for i in range(1, len(cleaned)):
        if cleaned[i]["at"] <= cleaned[i - 1]["at"]:
            cleaned[i]["at"] = cleaned[i - 1]["at"] + 1

    job_id = str(uuid.uuid4())
    now = _now_iso()
    out_path = settings.output_dir / f"{job_id}.funscript"
    from app.processing.funscript import write_funscript
    write_funscript(out_path, cleaned)
    # Snapshot as .original.funscript so Reset in the editor works
    # against the imported script rather than "no original."
    shutil.copy2(out_path, _original_path_of(out_path))

    with get_db() as db:
        db.execute(
            "INSERT INTO jobs(id, video_id, mode, params_json, status, progress, "
            "output_path, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                job_id, video_id, "imported",
                json.dumps({"source": "imported", "action_count": len(cleaned)}),
                "done", 1.0, str(out_path), now, now,
            ),
        )
    return {"job_id": job_id, "action_count": len(cleaned)}
