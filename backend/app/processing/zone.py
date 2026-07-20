from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from scipy.ndimage import maximum_filter1d, minimum_filter1d
from scipy.signal import find_peaks, savgol_filter

from app.config import settings
from app.processing.base import VideoInfo
from app.processing.funscript import write_funscript


class ZoneProcessor:
    """Lucas-Kanade optical flow inside a zone → per-frame vertical
    motion → Savitzky-Golay smoothing → peak/trough → funscript.

    Signal derivation
    -----------------
    Each frame we track the previous frame's features into the current
    frame with pyramidal LK. We take the *median* of surviving tracks'
    dy — a plain mean would be pulled around by the occasional bad
    track locking onto a moving highlight or an outlier disparity.

    Feature refresh
    ---------------
    When a track leaves the zone or the survivor count falls below a
    floor, we re-detect. Re-detection happens on the current frame, so
    the accumulated position isn't shifted; we just start a new set of
    tracks from the current geometry.

    Output shape
    ------------
    The raw signal is accumulated dy in pixels. Smoothing removes the
    per-frame LK noise; a rolling-window auto-range (local min→0, max→100
    over ~3s) maps to stroke position without flattening amplitude
    variation across sections. Peaks and troughs of the smoothed,
    normalized signal become actions — one per reversal — which matches
    how human-authored scripts look and keeps the file compact.

    Direction
    ---------
    Motion-signal peaks map to funscript pos=100 and troughs to pos=0
    by default. The sign is arbitrary — a zone drawn on something that
    moves opposite to the stroker's motion will come out inverted. The
    `invert` param in the job flips the mapping (peaks → 0, troughs → 100).
    """

    # These aren't in .env because most videos don't need to touch them —
    # the sensitivity dials the user actually reaches for (window,
    # prominence, min-distance) already live in Settings.
    _FEATURE_PARAMS = dict(maxCorners=200, qualityLevel=0.3,
                           minDistance=7, blockSize=7)
    _LK_PARAMS = dict(
        winSize=(15, 15),
        maxLevel=2,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03),
    )
    _MIN_TRACKS = 15  # refresh below this — sparse survivors produce noisy dy

    def run(
        self,
        video: VideoInfo,
        params: dict,
        out_path: Path,
        progress_cb: Callable[[float], None],
        debug_out_path: Path | None = None,
    ) -> None:
        zone = params.get("zone") or {}
        for k in ("x", "y", "w", "h"):
            if k not in zone:
                raise ValueError(f"zone param missing '{k}'")
        invert = bool(params.get("invert", False))

        zx = max(0, int(zone["x"] * video.width))
        zy = max(0, int(zone["y"] * video.height))
        zw = max(1, min(video.width - zx, int(zone["w"] * video.width)))
        zh = max(1, min(video.height - zy, int(zone["h"] * video.height)))

        cap = cv2.VideoCapture(str(video.path))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video.path}")

        fps = video.fps if video.fps > 0 else cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0

        ret, frame = cap.read()
        if not ret:
            cap.release()
            raise RuntimeError("empty video")

        prev_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = np.zeros_like(prev_gray)
        mask[zy:zy + zh, zx:zx + zw] = 255
        prev_pts = cv2.goodFeaturesToTrack(prev_gray, mask=mask, **self._FEATURE_PARAMS)

        positions: list[float] = [0.0]
        total_frames = max(1, int(video.duration_ms / 1000 * fps))
        last_progress_frame = 0
        frame_idx = 1

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                new_pos = positions[-1]
                if prev_pts is not None and len(prev_pts) >= 4:
                    new_pts, status, _ = cv2.calcOpticalFlowPyrLK(
                        prev_gray, curr_gray, prev_pts, None, **self._LK_PARAMS
                    )
                    if new_pts is not None:
                        good = status.flatten().astype(bool)
                        if good.any():
                            good_new = new_pts[good]
                            good_old = prev_pts[good]
                            dy = float(np.median(good_new[:, 0, 1] - good_old[:, 0, 1]))
                            new_pos = positions[-1] + dy
                            # Drop tracks that have left the zone — otherwise
                            # they anchor tracking to whatever's outside.
                            in_x = (good_new[:, 0, 0] >= zx) & (good_new[:, 0, 0] < zx + zw)
                            in_y = (good_new[:, 0, 1] >= zy) & (good_new[:, 0, 1] < zy + zh)
                            prev_pts = good_new[in_x & in_y]
                        else:
                            prev_pts = None
                    else:
                        prev_pts = None

                if prev_pts is None or len(prev_pts) < self._MIN_TRACKS:
                    prev_pts = cv2.goodFeaturesToTrack(
                        curr_gray, mask=mask, **self._FEATURE_PARAMS
                    )

                positions.append(new_pos)
                prev_gray = curr_gray
                frame_idx += 1

                # Reserve the last ~15% of the progress bar for smoothing
                # + peak detection so the UI doesn't stall at 100%.
                if frame_idx - last_progress_frame >= 30:
                    progress_cb(min(0.85, 0.85 * frame_idx / total_frames))
                    last_progress_frame = frame_idx
        finally:
            cap.release()

        actions, reversal_frames = self._extract_actions(
            np.array(positions, dtype=np.float64), fps, invert=invert,
        )
        write_funscript(out_path, actions)

        if debug_out_path is not None:
            from app.processing.debug import render_zone_debug
            progress_cb(0.92)
            render_zone_debug(
                source_video=video.path,
                out_path=debug_out_path,
                zone_px=(zx, zy, zw, zh),
                reversal_frame_indices=reversal_frames,
            )
        progress_cb(1.0)

    def _extract_actions(
        self, positions: np.ndarray, fps: float, *, invert: bool = False,
    ) -> tuple[list[dict], list[int]]:
        window = settings.smoothing_window
        polyorder = settings.smoothing_polyorder
        # savgol requires odd window; clamp to signal length; polyorder < window.
        if window % 2 == 0:
            window += 1
        n = len(positions)
        if window >= n:
            window = n if n % 2 == 1 else max(3, n - 1)
        polyorder = min(polyorder, window - 1)

        smoothed = savgol_filter(positions, window, polyorder) if n >= window else positions
        smoothed = np.asarray(smoothed, dtype=np.float64)

        if float(np.max(smoothed) - np.min(smoothed)) < 1e-3:
            # Nothing moved — one neutral action lets the funscript still
            # exist without pretending there was motion to report.
            return [{"at": 0, "pos": 50}], []

        # Rolling auto-range. `size` is total window; clamped to signal
        # length so short videos don't error out. scipy handles edges via
        # reflect mode, so a window larger than the signal degrades to
        # global min/max at every point (i.e., back to the old behavior).
        win_frames = max(3, int(settings.zone_rolling_window_ms / 1000 * fps))
        win_frames = min(win_frames, len(smoothed))
        local_min = minimum_filter1d(smoothed, size=win_frames)
        local_max = maximum_filter1d(smoothed, size=win_frames)
        # Floor the range so a still section can't amplify LK noise to
        # full-swing. When actual range < floor, values compress into a
        # narrow band low in the [0..100] scale and get filtered out by
        # PEAK_PROMINENCE downstream.
        local_range = np.maximum(
            local_max - local_min, float(settings.zone_min_amplitude_px)
        )
        normalized = (smoothed - local_min) / local_range * 100.0
        normalized = np.clip(normalized, 0.0, 100.0)
        if invert:
            normalized = 100.0 - normalized

        min_dist_frames = max(1, int(settings.peak_min_distance_ms / 1000 * fps))
        peaks, _ = find_peaks(
            normalized,
            prominence=settings.peak_prominence,
            distance=min_dist_frames,
        )
        troughs, _ = find_peaks(
            -normalized,
            prominence=settings.peak_prominence,
            distance=min_dist_frames,
        )

        indices = sorted(int(i) for i in list(peaks) + list(troughs))
        if not indices:
            return [{"at": 0, "pos": 50}], []

        actions: list[dict] = []
        for i in indices:
            at_ms = int(round(i / fps * 1000))
            pos = int(round(float(normalized[i])))
            actions.append({"at": at_ms, "pos": max(0, min(100, pos))})

        # Ensure strictly increasing timestamps — high-fps videos can
        # collide two adjacent reversals at the same ms.
        deduped: list[dict] = []
        for a in actions:
            if deduped and a["at"] <= deduped[-1]["at"]:
                a["at"] = deduped[-1]["at"] + 1
            deduped.append(a)
        return deduped, indices
