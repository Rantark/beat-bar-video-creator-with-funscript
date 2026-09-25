"""Pose-driven funscript generation via YOLOv8-pose.

Instead of watching pixels inside a rectangle (zone), a line-crossing
signal (line), or a color signal at a hit point (marker), the pose
processor tracks 17 anatomical keypoints per frame using a neural
body-pose model. The user picks which keypoint drives the funscript
— e.g. the hip for whole-body rhythmic motion, the wrist for a hand
that's the dominant moving element, or "auto" to let the pipeline
pick whichever keypoint moved the most on the vertical axis.

Content model
-------------
The pose model expects a person visible in the frame. It detects
zero-or-more people per frame; we lock onto the one with the highest
overall detection confidence in the first successful frame and follow
the same person by keeping the one whose bounding box overlaps the
previous frame's most (simple centroid distance heuristic).

Signal
------
For the chosen keypoint we sample the (x, y) pixel coordinates per
frame. Missing frames (occlusion, low confidence, no person) get
linearly interpolated so the downstream smoothing has a continuous
signal. The Y axis is the default because vertical motion is what a
stroker cares about, but the user can pick X or the magnitude of
motion (dx² + dy²) if the content is horizontal or diagonal.

Funscript shape
---------------
Signal → savgol smoothing → rolling-window auto-range normalization
→ 0..100 → scipy find_peaks for both peaks and troughs → funscript
actions. Same pipeline as zone mode.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from scipy.ndimage import maximum_filter1d, minimum_filter1d
from scipy.signal import find_peaks, savgol_filter

from app.config import settings
from app.processing.base import VideoInfo
from app.processing.device import resolve_device
from app.processing.funscript import write_funscript

# COCO-17 keypoint layout used by YOLOv8-pose. Kept as a dict so the
# frontend can display friendly names.
KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]


class PoseProcessor:
    def run(
        self,
        video: VideoInfo,
        params: dict,
        out_path: Path,
        progress_cb: Callable[[float], None],
        debug_out_path: Path | None = None,
    ) -> None:
        pose = params.get("pose") or {}
        keypoint = pose.get("keypoint", "auto")  # "auto" or an index/name
        axis = pose.get("axis", "y")             # y / x / magnitude
        confidence = float(pose.get("confidence_threshold", 0.3))
        invert = bool(pose.get("invert", False))
        resize_max = int(pose.get("resize_max", 640))  # long-edge cap for speed
        device, device_note = resolve_device(pose.get("device"))
        if device_note:
            print(f"[pose] {device_note}", flush=True)

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "Pose mode requires ultralytics — install with "
                "`pip install -e .[pose]` in the backend venv."
            ) from exc

        # Model auto-downloads to torch's hub cache on first use (~6.5 MB).
        model = YOLO("yolov8n-pose.pt")

        cap = cv2.VideoCapture(str(video.path))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video.path}")
        fps = video.fps if video.fps > 0 else cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = max(1, int(video.duration_ms / 1000 * fps))

        # Downscale wide/tall videos before inference so a 4K clip
        # doesn't cripple CPU throughput. Coordinates get rescaled back
        # to source pixels after inference so the downstream pipeline
        # is oblivious to the resize.
        w0, h0 = video.width, video.height
        scale = min(1.0, resize_max / max(w0, h0)) if resize_max > 0 else 1.0
        infer_w = int(w0 * scale)
        infer_h = int(h0 * scale)

        xy_series: list[tuple[float, float] | None] = []
        # Last chosen person centroid — helps re-lock to the same person
        # after brief occlusions. Simple heuristic: nearest centroid wins.
        last_centroid: tuple[float, float] | None = None

        frame_idx = 0
        last_progress = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if scale < 1.0:
                    frame = cv2.resize(frame, (infer_w, infer_h), interpolation=cv2.INTER_AREA)

                # verbose=False silences ultralytics's per-frame stdout spam.
                results = model.predict(
                    frame, verbose=False, conf=confidence, imgsz=infer_w,
                    device=device,
                )
                res = results[0] if results else None
                person_kpts = _pick_person(res, last_centroid)
                if person_kpts is None:
                    xy_series.append(None)
                else:
                    # keypoints_xy: (17, 2) — pixel coords in the resized frame.
                    xy_series.append(person_kpts)
                    # Update the centroid from the mean of visible torso points
                    # (shoulders + hips) so tracking is stable across occlusions
                    # that lose face keypoints.
                    torso = person_kpts[5:7 + 6:1]  # 5,6 shoulders; 11,12 hips
                    cx = float(np.mean(torso[:, 0]))
                    cy = float(np.mean(torso[:, 1]))
                    last_centroid = (cx, cy)

                frame_idx += 1
                if frame_idx - last_progress >= 30:
                    progress_cb(min(0.9, 0.9 * frame_idx / total_frames))
                    last_progress = frame_idx
        finally:
            cap.release()

        n = len(xy_series)
        if n < 4:
            write_funscript(out_path, [{"at": 0, "pos": 50}])
            progress_cb(1.0)
            return

        # Pick which keypoint to actually use. "auto" scans every keypoint
        # and picks the one with the highest vertical range across the clip.
        kp_idx = _resolve_keypoint(keypoint, xy_series)

        # Extract the chosen coordinate per frame. Missing frames become
        # NaN; we linearly interpolate through the gaps so the smoothing
        # step has a continuous signal.
        signal = np.full(n, np.nan, dtype=np.float64)
        for i, kpts in enumerate(xy_series):
            if kpts is None:
                continue
            x, y = float(kpts[kp_idx][0]), float(kpts[kp_idx][1])
            if axis == "x":
                signal[i] = x
            elif axis == "magnitude":
                # Distance from origin — usually not the right choice by
                # itself, but combined with keypoint="wrist" it can track
                # a swinging hand better than either axis alone.
                signal[i] = float(np.hypot(x, y))
            else:  # y
                signal[i] = y

        signal = _fill_nans(signal)
        if signal is None:
            write_funscript(out_path, [{"at": 0, "pos": 50}])
            progress_cb(1.0)
            return

        # Rescale to source-pixel space so the peak-detection thresholds
        # (`zone_min_amplitude_px`) are comparable across resize choices.
        if scale < 1.0:
            signal = signal / scale

        actions, reversal_indices = _signal_to_actions(signal, fps, invert=invert)
        write_funscript(out_path, actions)

        if debug_out_path is not None:
            from app.processing.debug import render_pose_debug
            progress_cb(0.92)
            render_pose_debug(
                source_video=video.path,
                out_path=debug_out_path,
                xy_series=xy_series,
                keypoint_index=kp_idx,
                axis=axis,
                scale=scale,
                reversal_frame_indices=reversal_indices,
            )
        progress_cb(1.0)


# --- Helpers ---------------------------------------------------------------


def _pick_person(res, last_centroid: tuple[float, float] | None) -> np.ndarray | None:
    """Pick one person's keypoints from a YOLOv8-pose result. Prefer the
    person whose torso centroid is nearest the previous frame's; on the
    first successful frame we take the highest-confidence detection."""
    if res is None or res.keypoints is None or res.keypoints.xy is None:
        return None
    all_kpts = res.keypoints.xy.cpu().numpy()  # (N, 17, 2)
    if all_kpts.size == 0:
        return None
    if len(all_kpts) == 1:
        return all_kpts[0]
    # Torso centroid per detected person.
    centroids = np.mean(all_kpts[:, [5, 6, 11, 12], :], axis=1)
    if last_centroid is None:
        # Take the person whose bounding box has the highest confidence.
        if res.boxes is not None and res.boxes.conf is not None:
            conf = res.boxes.conf.cpu().numpy()
            return all_kpts[int(np.argmax(conf))]
        return all_kpts[0]
    prev = np.asarray(last_centroid, dtype=np.float64)
    dists = np.linalg.norm(centroids - prev, axis=1)
    return all_kpts[int(np.argmin(dists))]


def _resolve_keypoint(spec, xy_series) -> int:
    """Turn a name, int, or 'auto' into an integer keypoint index."""
    if isinstance(spec, int) and 0 <= spec < 17:
        return spec
    if isinstance(spec, str):
        if spec == "auto":
            # Pick the keypoint with the largest vertical std across the
            # clip — that's the one most likely to carry rhythmic motion.
            ys = np.full((17, len(xy_series)), np.nan, dtype=np.float64)
            for i, kpts in enumerate(xy_series):
                if kpts is None:
                    continue
                ys[:, i] = kpts[:, 1]
            stds = np.nanstd(ys, axis=1)
            stds = np.nan_to_num(stds, nan=0.0)
            return int(np.argmax(stds))
        if spec in KEYPOINT_NAMES:
            return KEYPOINT_NAMES.index(spec)
    return KEYPOINT_NAMES.index("left_hip")


def _fill_nans(arr: np.ndarray) -> np.ndarray | None:
    """Linear interpolation through NaN runs. Returns None if the whole
    array is NaN (person never detected)."""
    mask = ~np.isnan(arr)
    if not mask.any():
        return None
    idx = np.arange(len(arr))
    return np.interp(idx, idx[mask], arr[mask])


def _signal_to_actions(
    positions: np.ndarray, fps: float, *, invert: bool = False,
) -> tuple[list[dict], list[int]]:
    """Same shape/normalization/peak-detection pipeline zone mode uses.
    Kept local (rather than imported from zone.py) so pose mode is
    self-contained and easy to tune without leaking regressions into
    the older modes."""
    window = settings.smoothing_window
    polyorder = settings.smoothing_polyorder
    if window % 2 == 0:
        window += 1
    n = len(positions)
    if window >= n:
        window = n if n % 2 == 1 else max(3, n - 1)
    polyorder = min(polyorder, window - 1)
    smoothed = savgol_filter(positions, window, polyorder) if n >= window else positions
    smoothed = np.asarray(smoothed, dtype=np.float64)

    if float(np.max(smoothed) - np.min(smoothed)) < 1e-3:
        return [{"at": 0, "pos": 50}], []

    win_frames = max(3, int(settings.zone_rolling_window_ms / 1000 * fps))
    win_frames = min(win_frames, len(smoothed))
    local_min = minimum_filter1d(smoothed, size=win_frames)
    local_max = maximum_filter1d(smoothed, size=win_frames)
    local_range = np.maximum(
        local_max - local_min, float(settings.zone_min_amplitude_px)
    )
    normalized = (smoothed - local_min) / local_range * 100.0
    normalized = np.clip(normalized, 0.0, 100.0)
    if invert:
        normalized = 100.0 - normalized

    min_dist_frames = max(1, int(settings.peak_min_distance_ms / 1000 * fps))
    peaks, _ = find_peaks(
        normalized, prominence=settings.peak_prominence, distance=min_dist_frames,
    )
    troughs, _ = find_peaks(
        -normalized, prominence=settings.peak_prominence, distance=min_dist_frames,
    )
    indices = sorted(int(i) for i in list(peaks) + list(troughs))
    if not indices:
        return [{"at": 0, "pos": 50}], []
    actions: list[dict] = []
    for i in indices:
        at_ms = int(round(i / fps * 1000))
        pos = int(round(float(normalized[i])))
        actions.append({"at": at_ms, "pos": max(0, min(100, pos))})
    deduped: list[dict] = []
    for a in actions:
        if deduped and a["at"] <= deduped[-1]["at"]:
            a["at"] = deduped[-1]["at"] + 1
        deduped.append(a)
    return deduped, indices
