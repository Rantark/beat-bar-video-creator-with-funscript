"""Annotated MP4 renderer for verifying what a processor "saw."

Draws the mode's chosen shape (zone rect, line + strip, or marker circle)
on every frame and flashes a red border + label whenever the processor
emitted an event at that frame. Audio from the source video is muxed in
so the user can hear beats sync with visible flashes — the fastest
sanity check for whether the algorithm caught the right thing.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Iterable

import cv2
import numpy as np

from app.config import settings

FLASH_MS = 150  # how long each event flash stays on screen


def render_marker_debug(
    source_video: Path,
    out_path: Path,
    marker_x_px: int,
    marker_y_px: int,
    marker_r_px: int,
    beat_frame_indices: Iterable[int],
) -> None:
    beat_set = set(int(i) for i in beat_frame_indices)

    def draw(frame: np.ndarray, frame_idx: int, flash_left: int) -> int:
        cv2.circle(frame, (marker_x_px, marker_y_px), marker_r_px, (0, 220, 220), 2)
        cv2.circle(frame, (marker_x_px, marker_y_px), 2, (0, 220, 220), -1)
        if frame_idx in beat_set:
            flash_left = 0  # will be set by caller to fps * FLASH_MS/1000
        return flash_left

    _render(
        source_video, out_path,
        draw_fn=draw,
        event_frames=beat_set,
        label="BEAT",
    )


def render_zone_debug(
    source_video: Path,
    out_path: Path,
    zone_px: tuple[int, int, int, int],
    reversal_frame_indices: Iterable[int],
) -> None:
    zx, zy, zw, zh = zone_px
    events = set(int(i) for i in reversal_frame_indices)

    def draw(frame: np.ndarray, frame_idx: int, flash_left: int) -> int:
        cv2.rectangle(frame, (zx, zy), (zx + zw, zy + zh), (0, 220, 220), 2)
        if frame_idx in events:
            flash_left = 0
        return flash_left

    _render(source_video, out_path, draw_fn=draw, event_frames=events, label="REVERSAL")


def render_audio_debug(
    source_video: Path,
    out_path: Path,
    beat_frame_indices: Iterable[int],
    beat_times_ms: Iterable[int],
    video_duration_ms: int,
    novelty: np.ndarray,
    novelty_hop_ms: float,
    bar_image: np.ndarray | None = None,
    hit_image: np.ndarray | None = None,
    beat_image: np.ndarray | None = None,
    lookahead_ms: int = 1500,
    progress_cb: Callable[[float], None] | None = None,
) -> None:
    """Rhythm-game style overlay: beats scroll right→left, crossing a
    fixed hit marker at exactly their onset time.

    Layout
    ------
      [ bar   [beat]  [beat]  [beat]  ← scrolling
        ↑hit marker (fixed at ~20% from left)
      ]

    Optional custom sprites
    -----------------------
    `bar_image`     — tiled/scaled across the strip background
    `hit_image`     — drawn at the fixed hit-marker position
    `beat_image`    — drawn for each scrolling beat (respects alpha)

    Falls back to drawn primitives (dark strip / white line / cyan
    circle) when a slot is None so the mode is useful without any
    uploads.
    """
    beats = sorted(int(t) for t in beat_times_ms)
    event_set = set(int(i) for i in beat_frame_indices)
    total_ms = max(1, int(video_duration_ms))
    lookback_ms = 400  # keep beats visible briefly after they hit
    _ = novelty, novelty_hop_ms  # currently unused in rhythm-game mode

    # Filled on the first draw call when we know the frame size, then
    # reused for every subsequent frame. This was the big win — the
    # previous code called cv2.resize on the bar every frame plus one
    # cv2.resize per visible beat per frame, which added up to minutes
    # of extra work on a 5-min clip.
    cache: dict = {}
    beats_arr = np.asarray(beats, dtype=np.int64)

    def draw(frame: np.ndarray, frame_idx: int, flash_left: int) -> int:
        if not cache:
            h, w = frame.shape[:2]
            bar_h = max(40, h // 8)
            bar_y = h - bar_h - 12
            bar_x1 = 20
            bar_x2 = w - 20
            bar_w = bar_x2 - bar_x1
            hit_x = bar_x1 + int(bar_w * 0.2)
            cache.update(
                bar_h=bar_h, bar_y=bar_y, bar_x1=bar_x1, bar_x2=bar_x2,
                bar_w=bar_w, hit_x=hit_x,
                px_per_ms=(bar_x2 - hit_x) / max(1, lookahead_ms),
                bar_scaled=(
                    cv2.resize(bar_image, (bar_w, bar_h), interpolation=cv2.INTER_LINEAR)
                    if bar_image is not None else None
                ),
                beat_prescaled=_prescale_sprite(beat_image, bar_h - 8),
                hit_prescaled=_prescale_sprite(hit_image, bar_h + 8),
            )
        bar_h = cache["bar_h"]
        bar_y = cache["bar_y"]
        bar_x1 = cache["bar_x1"]
        bar_x2 = cache["bar_x2"]
        hit_x = cache["hit_x"]
        px_per_ms = cache["px_per_ms"]

        # Background
        if cache["bar_scaled"] is not None:
            frame[bar_y:bar_y + bar_h, bar_x1:bar_x2] = cache["bar_scaled"]
        else:
            overlay = frame.copy()
            cv2.rectangle(
                overlay, (bar_x1, bar_y), (bar_x2, bar_y + bar_h),
                (20, 20, 20), -1,
            )
            cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, dst=frame)
            cv2.rectangle(
                frame, (bar_x1, bar_y), (bar_x2, bar_y + bar_h),
                (120, 120, 120), 1,
            )

        # Current playback time on the bar timeline.
        cursor_t_ms = 0
        if _cached_total_frames[0] > 0:
            cursor_t_ms = int(frame_idx * (total_ms / _cached_total_frames[0]))

        # Scrolling beats — binary-search the visible window instead of
        # scanning the full list per frame.
        window_lo = cursor_t_ms - lookback_ms
        window_hi = cursor_t_ms + lookahead_ms
        if beats_arr.size:
            lo_i = int(np.searchsorted(beats_arr, window_lo, side="left"))
            hi_i = int(np.searchsorted(beats_arr, window_hi, side="right"))
            for i in range(lo_i, hi_i):
                t = int(beats_arr[i])
                x = hit_x + int((t - cursor_t_ms) * px_per_ms)
                if x < bar_x1 - 40 or x > bar_x2 + 40:
                    continue
                _draw_beat_sprite_prescaled(frame, x, bar_y, bar_h, cache["beat_prescaled"])

        # Hit marker on top of everything.
        _draw_hit_sprite_prescaled(frame, hit_x, bar_y, bar_h, cache["hit_prescaled"])

        # No red flash / BEAT label here — the moving beat bar IS the
        # visualization, so the border strobe is just noise. We still
        # need `flash_left` for _render's signature but keep it at -1.
        return flash_left

    _render(
        source_video, out_path,
        draw_fn=draw,
        event_frames=set(),  # suppresses the border flash overlay
        label="BEAT",
        progress_cb=progress_cb,
    )


def _prescale_sprite(sprite: np.ndarray | None, target_h: int) -> np.ndarray | None:
    if sprite is None or sprite.size == 0 or target_h <= 0:
        return None
    sh, sw = sprite.shape[:2]
    scale = target_h / sh
    tw = max(1, int(round(sw * scale)))
    th = max(1, target_h)
    return cv2.resize(sprite, (tw, th), interpolation=cv2.INTER_LINEAR)


def _draw_beat_sprite_prescaled(
    frame: np.ndarray, cx: int, bar_y: int, bar_h: int,
    sprite: np.ndarray | None,
) -> None:
    if sprite is None:
        cy = bar_y + bar_h // 2
        r = max(6, bar_h // 3)
        cv2.circle(frame, (cx, cy), r, (0, 220, 220), -1)
        cv2.circle(frame, (cx, cy), r, (30, 30, 30), 2)
        return
    _paste_bgra_prescaled(frame, sprite, cx, bar_y + bar_h // 2)


def _draw_hit_sprite_prescaled(
    frame: np.ndarray, cx: int, bar_y: int, bar_h: int,
    sprite: np.ndarray | None,
) -> None:
    if sprite is None:
        cv2.line(
            frame, (cx, bar_y - 6), (cx, bar_y + bar_h + 6),
            (240, 240, 240), 3,
        )
        cv2.circle(frame, (cx, bar_y + bar_h // 2), 8, (240, 240, 240), 2)
        return
    _paste_bgra_prescaled(frame, sprite, cx, bar_y + bar_h // 2)


def _paste_bgra_prescaled(
    frame: np.ndarray, resized: np.ndarray, cx: int, cy: int,
) -> None:
    """Paste a pre-resized BGRA sprite centered at (cx, cy). Respects
    alpha. Clips against the frame bounds."""
    th, tw = resized.shape[:2]
    x1 = cx - tw // 2
    y1 = cy - th // 2
    x2 = x1 + tw
    y2 = y1 + th
    fh, fw = frame.shape[:2]
    sx1 = max(0, -x1)
    sy1 = max(0, -y1)
    sx2 = tw - max(0, x2 - fw)
    sy2 = th - max(0, y2 - fh)
    dx1 = max(0, x1)
    dy1 = max(0, y1)
    dx2 = min(fw, x2)
    dy2 = min(fh, y2)
    if dx2 <= dx1 or dy2 <= dy1:
        return
    patch = resized[sy1:sy2, sx1:sx2]
    if patch.shape[2] == 4:
        rgb = patch[:, :, :3].astype(np.float32)
        a = patch[:, :, 3:4].astype(np.float32) / 255.0
        bg = frame[dy1:dy2, dx1:dx2].astype(np.float32)
        blended = rgb * a + bg * (1.0 - a)
        frame[dy1:dy2, dx1:dx2] = blended.astype(np.uint8)
    else:
        frame[dy1:dy2, dx1:dx2] = patch


# Populated by _render before draw_fn is invoked, so the audio-mode
# draw can convert a frame index to a time-position on the bar without
# re-opening the video. Simple 1-element list because closures can't
# easily rebind a module-level int without `global`.
_cached_total_frames = [0]


def render_line_debug(
    source_video: Path,
    out_path: Path,
    orientation: str,
    line_pts: tuple[int, int, int, int],  # x1,y1,x2,y2
    strip_rect: tuple[int, int, int, int],  # x,y,w,h of strip zone
    crossing_frame_indices: Iterable[int],
) -> None:
    x1, y1, x2, y2 = line_pts
    sx, sy, sw, sh = strip_rect
    events = set(int(i) for i in crossing_frame_indices)

    def draw(frame: np.ndarray, frame_idx: int, flash_left: int) -> int:
        # Strip zone (translucent) — approximate by a rectangle overlay
        overlay = frame.copy()
        cv2.rectangle(overlay, (sx, sy), (sx + sw, sy + sh), (0, 200, 0), -1)
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, dst=frame)
        # Line segment
        cv2.line(frame, (x1, y1), (x2, y2), (0, 220, 0), 3)
        if frame_idx in events:
            flash_left = 0
        return flash_left

    _render(source_video, out_path, draw_fn=draw, event_frames=events, label="CROSS")


def _render(
    source_video: Path,
    out_path: Path,
    draw_fn,
    event_frames: set[int],
    label: str,
    progress_cb: Callable[[float], None] | None = None,
) -> None:
    """Common frame loop + H264 encoder + audio mux."""
    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open source: {source_video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    flash_frames = max(1, int(fps * FLASH_MS / 1000))
    # Exposed to draw_fn (audio mode uses it for the playhead cursor
    # on the beat bar). CAP_PROP_FRAME_COUNT is approximate for some
    # containers but good enough for a visual cursor.
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    _cached_total_frames[0] = total_frames

    # Encoder: raw BGR frames → H264 via ffmpeg stdin. Faster and more
    # portable than OpenCV's VideoWriter, which on Windows often ships
    # only mp4v (MPEG-4 Part 2) that doesn't play in mobile browsers.
    tmp_video = out_path.with_suffix(".noaudio.mp4")
    tmp_video.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = [
        settings.ffmpeg_path,
        "-y",
        "-loglevel", "error",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{w}x{h}",
        "-pix_fmt", "bgr24",
        "-r", f"{fps}",
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "24",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(tmp_video),
    ]
    proc = subprocess.Popen(ffmpeg, stdin=subprocess.PIPE)
    assert proc.stdin is not None

    frame_idx = 0
    flash_left = -1
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            flash_left = draw_fn(frame, frame_idx, flash_left)
            if frame_idx in event_frames:
                flash_left = flash_frames
            if flash_left > 0:
                cv2.rectangle(frame, (2, 2), (w - 3, h - 3), (0, 0, 255), 6)
                cv2.putText(
                    frame, label, (16, 48),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 255), 3, cv2.LINE_AA,
                )
                flash_left -= 1
            proc.stdin.write(frame.tobytes())
            frame_idx += 1
            if progress_cb and total_frames > 0 and frame_idx % 30 == 0:
                progress_cb(min(1.0, frame_idx / total_frames))
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        proc.wait()

    # Mux source audio onto the annotated video. Copy video, re-encode
    # audio (AAC is universally supported). If source has no audio the
    # mux falls back to video-only rather than fail.
    mux = [
        settings.ffmpeg_path,
        "-y",
        "-loglevel", "error",
        "-i", str(tmp_video),
        "-i", str(source_video),
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0?",  # ? = optional; skip if source has no audio track
        "-shortest",
        str(out_path),
    ]
    result = subprocess.run(mux, capture_output=True)
    if result.returncode != 0:
        # Audio mux failed — keep the video-only file so the debug output
        # still exists (just silent). Common on synthetic clips.
        tmp_video.replace(out_path)
    else:
        tmp_video.unlink(missing_ok=True)
