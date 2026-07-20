from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from scipy.signal import find_peaks

from app.config import settings
from app.processing import beat_actions
from app.processing.base import VideoInfo
from app.processing.funscript import write_funscript
from app.processing.images import decode_data_url


class MarkerProcessor:
    """Point-color beat detector for rhythm-game / UI-overlay content.

    Content model
    -------------
    Beats are discrete events at a fixed pixel location — e.g. a ring
    marker landing on a hit point in a rhythm-game overlay. The
    algorithm is content-agnostic about what the "beat" looks like: it
    just watches a small circle of pixels and looks for moments when
    that region's color deviates significantly from its own rolling-
    median baseline. Works whether the beat is a color change, an icon
    appearing, or an animation firing there.

    Signal
    ------
    Two components combined so the detector works on both animated and
    solid-background content:
      * contrast (spatial): mean color of a small inner disc at the hit
        point vs. a surrounding annulus. Robust to animated backgrounds
        because both regions see the same background changes — only a
        marker specifically overlaying the inner disc lights this up.
      * delta (temporal): frame-to-frame change in the inner mean.
        Kept as a secondary signal for solid-background content where a
        same-colored marker doesn't produce spatial contrast.
    signal = contrast_weight * contrast + delta_weight * delta.
    Peaks in `signal` → beat events.

    Funscript shape
    ---------------
    Both stroke endpoints vary with speed. Slow strokes go max_down →
    max_up (full amplitude); fast strokes go max_down_fast → max_up_fast
    (shorter). Intermediate speeds interpolate on both ends independently.

      * (0, pos=up_for(first_interval))    — start at the appropriate up
      * (t_beat, pos=down_for(incoming))   — beat depth per incoming interval
      * ((t_i + t_{i+1}) / 2, pos=up_for(outgoing)) — upstroke peak per outgoing
      * (t_last, pos=down_for(...))        — end at the last beat's depth
    """

    def run(
        self,
        video: VideoInfo,
        params: dict,
        out_path: Path,
        progress_cb: Callable[[float], None],
        debug_out_path: Path | None = None,
    ) -> None:
        marker = params.get("marker") or {}
        cx_n = float(marker.get("x", 0.5))
        cy_n = float(marker.get("y", 0.5))
        r_n = float(marker.get("radius", 0.02))
        # Stroke shape params — defaults are backward-compatible
        # (fast values == slow values means no per-speed adaptation).
        max_up = float(marker.get("max_up", 100))
        max_down = float(marker.get("max_down", 0))
        max_up_fast = float(marker.get("max_up_fast", max_up))
        max_down_fast = float(marker.get("max_down_fast", max_down))
        # Clamp each to [0, 100], then enforce full ordering:
        # max_down <= max_down_fast <= max_up_fast <= max_up.
        max_up = max(0.0, min(100.0, max_up))
        max_down = max(0.0, min(100.0, max_down))
        max_up_fast = max(0.0, min(100.0, max_up_fast))
        max_down_fast = max(0.0, min(100.0, max_down_fast))
        if max_down > max_up:
            max_down, max_up = max_up, max_down
        max_up_fast = max(max_down, min(max_up, max_up_fast))
        max_down_fast = max(max_down, min(max_up_fast, max_down_fast))

        # Section shaping — per-job overrides fall back to env defaults.
        variety_amount = max(
            0.0, min(1.0, float(marker.get("variety_amount", settings.marker_variety_amount))),
        )
        idle_enabled = bool(marker.get("idle_enabled", settings.marker_idle_enabled))
        motion_smoothing = max(
            0, min(4, int(marker.get("motion_smoothing", settings.marker_motion_smoothing))),
        )
        # Beat sensitivity as 0..1 maps to prominence via a linear
        # sweep: 0 → strict (prominence 25), 1 → permissive (prominence 5).
        # Default sensitivity 0.5 reproduces the previous default of 15.
        # Passing prominence directly still overrides.
        sensitivity = marker.get("sensitivity")
        if sensitivity is not None:
            s = max(0.0, min(1.0, float(sensitivity)))
            prominence_val = 25.0 - 20.0 * s
        else:
            prominence_val = float(settings.marker_prominence)

        # Optional template — a base64 image data URL captured by the
        # frontend from a frame where the beat is visible. When present
        # we add cv2.matchTemplate scores as an extra signal component,
        # which is much more discriminative than color statistics for
        # markers with a consistent visual pattern.
        template_img = decode_data_url(marker.get("template"))

        cx_px = int(cx_n * video.width)
        cy_px = int(cy_n * video.height)
        r_px = max(2, int(r_n * min(video.width, video.height)))

        cap = cv2.VideoCapture(str(video.path))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video.path}")
        fps = video.fps if video.fps > 0 else cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0

        # Two ROIs: an inner disc at the hit point and an outer annulus
        # around it. Their color difference is the primary "marker
        # present" signal — the animation underneath the overlay affects
        # both regions identically, so the differential cancels it out.
        r_outer_end = max(r_px + 1, int(r_px * settings.marker_outer_end_factor))
        r_outer_start = max(r_px, int(r_px * settings.marker_outer_start_factor))
        y1 = max(0, cy_px - r_outer_end)
        y2 = min(video.height, cy_px + r_outer_end + 1)
        x1 = max(0, cx_px - r_outer_end)
        x2 = min(video.width, cx_px + r_outer_end + 1)
        yy, xx = np.mgrid[y1:y2, x1:x2]
        dist_sq = (yy - cy_px) ** 2 + (xx - cx_px) ** 2
        inner_mask = dist_sq <= r_px * r_px
        outer_mask = (dist_sq >= r_outer_start * r_outer_start) & (
            dist_sq <= r_outer_end * r_outer_end
        )
        # If the marker sits near a frame edge and the outer annulus
        # gets clipped down to nothing, fall back gracefully — contrast
        # will just be 0 and delta will carry the signal.
        outer_ok = bool(outer_mask.any())

        # Template-matching search area — a bit larger than the template
        # to allow the marker to move within it between frames. We only
        # match inside this ROI, not the whole frame, so per-frame cost
        # stays cheap regardless of resolution.
        template_scores: list[float] | None = None
        tmpl_search: tuple[int, int, int, int] | None = None
        if template_img is not None:
            th, tw = template_img.shape[:2]
            search_r = max(th, tw)
            ty1 = max(0, cy_px - search_r)
            ty2 = min(video.height, cy_px + search_r)
            tx1 = max(0, cx_px - search_r)
            tx2 = min(video.width, cx_px + search_r)
            if ty2 - ty1 >= th and tx2 - tx1 >= tw:
                tmpl_search = (tx1, ty1, tx2, ty2)
                template_scores = []
            else:
                # Search area smaller than template — template useless here.
                template_img = None

        total_frames = max(1, int(video.duration_ms / 1000 * fps))
        inner_colors: list[tuple[float, float, float]] = []
        outer_colors: list[tuple[float, float, float]] = []
        frame_idx = 0
        last_progress_frame = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                roi = frame[y1:y2, x1:x2]
                if roi.size and inner_mask.any():
                    inner_m = roi[inner_mask].mean(axis=0)
                    inner_colors.append(
                        (float(inner_m[0]), float(inner_m[1]), float(inner_m[2]))
                    )
                else:
                    inner_colors.append((0.0, 0.0, 0.0))
                if roi.size and outer_ok:
                    outer_m = roi[outer_mask].mean(axis=0)
                    outer_colors.append(
                        (float(outer_m[0]), float(outer_m[1]), float(outer_m[2]))
                    )
                else:
                    outer_colors.append((0.0, 0.0, 0.0))
                if template_scores is not None and tmpl_search is not None:
                    tx1, ty1_, tx2, ty2_ = tmpl_search
                    search = frame[ty1_:ty2_, tx1:tx2]
                    try:
                        r = cv2.matchTemplate(
                            search, template_img, cv2.TM_CCOEFF_NORMED,
                        )
                        template_scores.append(float(r.max()))
                    except cv2.error:
                        template_scores.append(0.0)
                frame_idx += 1
                if frame_idx - last_progress_frame >= 60:
                    progress_cb(min(0.9, 0.9 * frame_idx / total_frames))
                    last_progress_frame = frame_idx
        finally:
            cap.release()

        n = len(inner_colors)
        if n < 3:
            write_funscript(out_path, [{"at": 0, "pos": 50}])
            progress_cb(1.0)
            return

        inner_arr = np.asarray(inner_colors, dtype=np.float64)  # (T, 3)
        outer_arr = np.asarray(outer_colors, dtype=np.float64)  # (T, 3)

        # Spatial contrast — how different the inner disc is from its
        # immediate surroundings each frame. Normalized to 0..100 by the
        # max possible L2 in BGR space (sqrt(3)*255 ≈ 441.67).
        if outer_ok:
            contrast = np.linalg.norm(inner_arr - outer_arr, axis=1) / 4.4167
        else:
            contrast = np.zeros(n, dtype=np.float64)

        # Temporal delta on the inner region — kept as a secondary
        # signal for solid-background content where a same-colored
        # marker doesn't produce spatial contrast.
        delta = np.zeros(n, dtype=np.float64)
        if n > 1:
            delta[1:] = np.linalg.norm(np.diff(inner_arr, axis=0), axis=1) / 4.4167

        # HSV distances between the inner mean and outer mean per frame.
        # Convert once as an (N, 1, 3) uint8 array so OpenCV's colorspace
        # conversion works on the batch.
        def _to_hsv(bgr_arr: np.ndarray) -> np.ndarray:
            b = np.clip(bgr_arr, 0, 255).astype(np.uint8).reshape(-1, 1, 3)
            return cv2.cvtColor(b, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float64)

        if outer_ok:
            inner_hsv = _to_hsv(inner_arr)
            outer_hsv = _to_hsv(outer_arr)
            # Hue is circular 0..179 in OpenCV — wrap the distance.
            hue_diff = np.abs(inner_hsv[:, 0] - outer_hsv[:, 0])
            hue_dist = np.minimum(hue_diff, 180.0 - hue_diff) / 90.0 * 100.0
            # Saturation 0..255 → 0..100.
            sat_dist = np.abs(inner_hsv[:, 1] - outer_hsv[:, 1]) / 2.55
        else:
            hue_dist = np.zeros(n, dtype=np.float64)
            sat_dist = np.zeros(n, dtype=np.float64)

        signal = (
            settings.marker_contrast_weight * contrast
            + settings.marker_delta_weight * delta
            + settings.marker_hue_weight * hue_dist
            + settings.marker_sat_weight * sat_dist
        )
        # Template score is 0..1 (TM_CCOEFF_NORMED); scale to 0..100.
        if template_scores is not None and len(template_scores) == n:
            tmpl = np.asarray(template_scores, dtype=np.float64) * 100.0
            signal = signal + settings.marker_template_weight * tmpl

        min_dist = max(1, int(settings.marker_min_distance_ms / 1000 * fps))
        peaks, _ = find_peaks(
            signal,
            prominence=prominence_val,
            distance=min_dist,
        )
        beat_frames = [int(p) for p in peaks]
        beat_ms = [int(round(f / fps * 1000)) for f in beat_frames]

        actions = beat_actions.beats_to_actions(
            beat_ms, video.duration_ms,
            max_up=max_up, max_down=max_down,
            max_up_fast=max_up_fast, max_down_fast=max_down_fast,
            variety_amount=variety_amount,
            idle_enabled=idle_enabled,
            motion_smoothing=motion_smoothing,
        )
        write_funscript(out_path, actions)

        if debug_out_path is not None:
            # Late import to avoid pulling ffmpeg dependency into the
            # non-debug path.
            from app.processing.debug import render_marker_debug
            progress_cb(0.92)
            render_marker_debug(
                source_video=video.path,
                out_path=debug_out_path,
                marker_x_px=cx_px,
                marker_y_px=cy_px,
                marker_r_px=r_px,
                beat_frame_indices=beat_frames,
            )
        progress_cb(1.0)

