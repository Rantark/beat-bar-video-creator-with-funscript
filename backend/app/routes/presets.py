"""Saved shape/musical/motion profiles.

Presets store only the *tuning* knobs (max_up/down, variety, smoothing,
sensitivity, etc.) — never spatial placement (marker x/y/radius, line
x/y/length). That way a preset works across any video: you save "Tighter
peaks for rhythm games" once, apply it wherever, and only place the
marker on each new clip.
"""
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.db import get_db

router = APIRouter(prefix="/api/presets", tags=["presets"])


VALID_MODES = ("marker", "line")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "mode": row["mode"],
        "params": json.loads(row["params_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("")
def list_presets(mode: str | None = None):
    with get_db() as db:
        if mode is not None:
            rows = db.execute(
                "SELECT * FROM presets WHERE mode=? ORDER BY name COLLATE NOCASE",
                (mode,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM presets ORDER BY mode, name COLLATE NOCASE",
            ).fetchall()
    return [_row_dict(r) for r in rows]


@router.post("")
def create_preset(payload: dict):
    name = (payload.get("name") or "").strip()
    mode = payload.get("mode")
    params = payload.get("params")
    if not name:
        raise HTTPException(400, "name required")
    if mode not in VALID_MODES:
        raise HTTPException(400, f"mode must be one of {VALID_MODES}")
    if not isinstance(params, dict):
        raise HTTPException(400, "params must be an object")

    preset_id = str(uuid.uuid4())
    now = _now_iso()
    with get_db() as db:
        db.execute(
            "INSERT INTO presets(id,name,mode,params_json,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (preset_id, name[:120], mode, json.dumps(params), now, now),
        )
        row = db.execute("SELECT * FROM presets WHERE id=?", (preset_id,)).fetchone()
    return _row_dict(row)


@router.put("/{preset_id}")
def update_preset(preset_id: str, payload: dict):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM presets WHERE id=?", (preset_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "preset not found")
        name = payload.get("name")
        params = payload.get("params")
        if name is not None:
            name = (name or "").strip()
            if not name:
                raise HTTPException(400, "name cannot be blank")
        if params is not None and not isinstance(params, dict):
            raise HTTPException(400, "params must be an object")
        db.execute(
            "UPDATE presets SET name=?, params_json=?, updated_at=? WHERE id=?",
            (
                name[:120] if name is not None else row["name"],
                json.dumps(params) if params is not None else row["params_json"],
                _now_iso(),
                preset_id,
            ),
        )
        row = db.execute("SELECT * FROM presets WHERE id=?", (preset_id,)).fetchone()
    return _row_dict(row)


@router.delete("/{preset_id}")
def delete_preset(preset_id: str):
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM presets WHERE id=?", (preset_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "preset not found")
        db.execute("DELETE FROM presets WHERE id=?", (preset_id,))
    return {"ok": True}
