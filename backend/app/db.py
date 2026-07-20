import sqlite3
from contextlib import contextmanager

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    duration_ms INTEGER,
    width INTEGER,
    height INTEGER,
    fps REAL,
    sprite_ready INTEGER NOT NULL DEFAULT 0,
    sprite_cols INTEGER,
    sprite_rows INTEGER,
    sprite_interval_ms INTEGER,
    sprite_thumb_width INTEGER,
    sprite_thumb_height INTEGER,
    source_type TEXT NOT NULL DEFAULT 'upload',
    source_url TEXT,
    download_status TEXT,
    download_progress REAL NOT NULL DEFAULT 0,
    download_error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    total_size INTEGER NOT NULL,
    chunk_size INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL,
    received_chunks TEXT NOT NULL DEFAULT '[]',
    video_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    params_json TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    output_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id)
);

CREATE TABLE IF NOT EXISTS presets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,          -- 'marker' | 'line' (spatial fields NOT saved)
    params_json TEXT NOT NULL,   -- only the tuning knobs, not placement
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def init_db() -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.db_path) as conn:
        # WAL is a persisted attribute — only needs to be set once. It
        # lets the poller read job progress while the BackgroundTask writes.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns to existing installs without a formal migration tool.

    SQLite has no `ADD COLUMN IF NOT EXISTS`, so we introspect and no-op
    if the column already exists. Cheap on startup and keeps user DBs
    upgradable.
    """
    def add(table: str, col: str, ddl: str) -> None:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    # URL-ingest state on the videos row.
    add("videos", "source_type", "source_type TEXT NOT NULL DEFAULT 'upload'")
    add("videos", "source_url", "source_url TEXT")
    add("videos", "download_status", "download_status TEXT")
    add("videos", "download_progress", "download_progress REAL NOT NULL DEFAULT 0")
    add("videos", "download_error", "download_error TEXT")


@contextmanager
def get_db():
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
