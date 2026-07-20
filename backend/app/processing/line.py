from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from app.config import settings
from app.processing import beat_actions
from app.processing.base import VideoInfo
from app.processing.funscript import write_funscript


class LineProcessor:
    """MOG2 background subtraction → strip-filtered largest-contour
    centroid → line-crossing events → funscript actions via the shared
    beat_actions pipeline (same shape/musical/smoothing knobs as marker
    mode).

    Line geometry
    -------------
    The line is a finite segment centered at (x, y) with a length along
    its orientation axis. Only contours whose centroid falls inside
    the line's extent plus a fixed perpendicular strip (LINE_STRIP_FRACTION
    on each side) are considered. That's what keeps distant background
    motion — an animated logo, a scrolling ticker, a hand crossing the
    scene — from stealing the "largest contour" and producing false
    crossings.

    Assumes one dominant moving object inside the strip per frame. When
    there isn't one (empty frame, occlusion), we skip that frame; false
    positives are worse than missed strokes because they show up as
    wrong actions the user has to edit out later.

    Direction of crossing is not encoded; consecutive crossings alternate
    pos=100 / pos=0. Physically, a real crossing sequence has to alternate
    directions anyway (an object can't cross the same way twice without
    coming back first).
    """

    # Matches LINE_STRIP_FRACTION in frontend/src/types.ts — the two must
    # stay in sync so the visualization reflects what's actually filtered.
    _STRIP_FRACTION = 0.2
    _WARMUP_FRAMES = 30  # MOG2 background model is noisy for ~1 second

    # Hysteresis band around the line as a fraction of the perpendicular
    # dimension. Without it, mask-edge jitter of ±1 px at the crossing
    # instant produces a phantom re-crossing ~100ms later — cleanly
    # observed on the moving-square test as an extra event per crossing.
    # 0.5% is ~2 px on 360p, ~5 px on 1080p; small enough that a real
    # crossing still trips it.
    _HYSTERESIS_FRACTION = 0.005

    def run(
        self,
        video: VideoInfo,
        params: dict,
        out_path: Path,
        progress_cb: Callable[[float], None],
        debug_out_path: Path | None = None,
    ) -> None:
        line = params.get("line") or {}
        orientation = line.get("orientation")
        cx_n = float(line.get("x", 0.5))
        cy_n = float(line.get("y", 0.5))
        length_n = float(line.get("length", 1.0))
        if orientation not in ("horizontal", "vertical"):
            raise ValueError(f"bad orientation: {orientation!r}")

        # Shape/musical/smoothing params (same knobs marker mode has).
        # Defaults are backward-compatible: max_up/down at 100/0 with
        # fast=slow means "hard 0↔100 alternation" which matches the
        # previous line-mode behavior once motion_smoothing=0.
        max_up = float(line.get("max_up", 100))
        max_down = float(line.get("max_down", 0))
        max_up_fast = float(line.get("max_up_fast", max_up))
        max_down_fast = float(line.get("max_down_fast", max_down))
        variety_amount = max(0.0, min(1.0, float(
            line.get("variety_amount", settings.marker_variety_amount)
        )))
        idle_enabled = bool(
            line.get("idle_enabled", settings.marker_idle_enabled)
        )
        motion_smoothing = max(0, min(4, int(
            line.get("motion_smoothing", settings.marker_motion_smoothing)
        )))

        cap = cv2.VideoCapture(str(video.path))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video.path}")
        fps = video.fps if video.fps > 0 else cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0

        # Pixel-space bounds. Along-line coords cover the segment;
        # perpendicular coords cover the strip.
        cx_px = cx_n * video.width
        cy_px = cy_n * video.height
        half_L_px = length_n * (video.width if orientation == "horizontal" else video.height) / 2
        half_strip_px = self._STRIP_FRACTION * (
            video.height if orientation == "horizontal" else video.width
        ) / 2

        if orientation == "horizontal":
            along_min, along_max = cx_px - half_L_px, cx_px + half_L_px
            perp_min, perp_max = cy_px - half_strip_px, cy_px + half_strip_px
            line_perp = cy_px
            hysteresis_px = max(1.0, video.height * self._HYSTERESIS_FRACTION)
        else:
            along_min, along_max = cy_px - half_L_px, cy_px + half_L_px
            perp_min, perp_max = cx_px - half_strip_px, cx_px + half_strip_px
            line_perp = cx_px
            hysteresis_px = max(1.0, video.width * self._HYSTERESIS_FRACTION)

        bg = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=25, detectShadows=False
        )
        total_frames = max(1, int(video.duration_ms / 1000 * fps))
        min_area = max(100, video.width * video.height // 5000)
        kernel = np.ones((3, 3), np.uint8)

        try:
            for _ in range(min(self._WARMUP_FRAMES, total_frames)):
                ret, frame = cap.read()
                if not ret:
                    raise RuntimeError("video too short to build background model")
                bg.apply(frame)

            prev_side: int | None = None
            events_ms: list[int] = []
            event_frames: list[int] = []
            frame_idx = self._WARMUP_FRAMES
            last_progress_frame = 0

            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                fg = bg.apply(frame)
                _, fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)
                fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)

                contours, _ = cv2.findContours(
                    fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                )

                # Filter contours by BBOX intersection with the strip —
                # not by centroid — so we don't reject the object at the
                # frames where its centroid drifts slightly outside the
                # strip's along-axis extent. Then take the largest
                # surviving contour's real (full-shape) centroid.
                best_area = 0.0
                best_perp = 0.0
                for c in contours:
                    area = cv2.contourArea(c)
                    if area < min_area or area <= best_area:
                        continue
                    bx, by, bw, bh = cv2.boundingRect(c)
                    if orientation == "horizontal":
                        # Does bbox intersect the strip rectangle?
                        if bx + bw < along_min or bx > along_max:
                            continue
                        if by + bh < perp_min or by > perp_max:
                            continue
                    else:
                        if by + bh < along_min or by > along_max:
                            continue
                        if bx + bw < perp_min or bx > perp_max:
                            continue
                    M = cv2.moments(c)
                    if M["m00"] == 0:
                        continue
                    ccx = M["m10"] / M["m00"]
                    ccy = M["m01"] / M["m00"]
                    best_area = area
                    best_perp = ccy if orientation == "horizontal" else ccx

                if best_area > 0:
                    # Hysteresis: only commit a side when the centroid is
                    # clearly past the line. In the dead-band we hold the
                    # previous side, killing mask-edge jitter.
                    if best_perp > line_perp + hysteresis_px:
                        side = 1
                    elif best_perp < line_perp - hysteresis_px:
                        side = -1
                    else:
                        side = prev_side
                    if (
                        side is not None
                        and prev_side is not None
                        and side != prev_side
                    ):
                        events_ms.append(int(round(frame_idx / fps * 1000)))
                        event_frames.append(frame_idx)
                    if side is not None:
                        prev_side = side
                # When no qualifying contour is found we keep prev_side
                # rather than reset — a brief occlusion followed by a
                # legitimate crossing on the other side still fires.

                frame_idx += 1
                if frame_idx - last_progress_frame >= 30:
                    progress_cb(min(0.98, frame_idx / total_frames))
                    last_progress_frame = frame_idx
        finally:
            cap.release()

        gap_ms = settings.peak_min_distance_ms
        filtered: list[int] = []
        filtered_frames: list[int] = []
        for t, fr in zip(events_ms, event_frames):
            if filtered and t - filtered[-1] < gap_ms:
                continue
            filtered.append(t)
            filtered_frames.append(fr)

        # Same downstream pipeline as marker mode — sections, variety,
        # smoothing, idle. Line crossings ARE beat events, so this is
        # the same problem shape.
        actions = beat_actions.beats_to_actions(
            filtered, video.duration_ms,
            max_up=max_up, max_down=max_down,
            max_up_fast=max_up_fast, max_down_fast=max_down_fast,
            variety_amount=variety_amount,
            idle_enabled=idle_enabled,
            motion_smoothing=motion_smoothing,
        )
        write_funscript(out_path, actions)

        if debug_out_path is not None:
            from app.processing.debug import render_line_debug
            progress_cb(0.92)
            # Compute line endpoints + strip rect in pixels for overlay.
            if orientation == "horizontal":
                lx1, ly1 = int(along_min), int(line_perp)
                lx2, ly2 = int(along_max), int(line_perp)
                strip = (int(along_min), int(perp_min),
                         int(along_max - along_min), int(perp_max - perp_min))
            else:
                lx1, ly1 = int(line_perp), int(along_min)
                lx2, ly2 = int(line_perp), int(along_max)
                strip = (int(perp_min), int(along_min),
                         int(perp_max - perp_min), int(along_max - along_min))
            render_line_debug(
                source_video=video.path,
                out_path=debug_out_path,
                orientation=orientation,
                line_pts=(lx1, ly1, lx2, ly2),
                strip_rect=strip,
                crossing_frame_indices=filtered_frames,
            )
        progress_cb(1.0)
