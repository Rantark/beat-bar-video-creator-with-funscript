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

# Keypoint groups — averaging multiple keypoints' motion produces a
# signal that's robust against single-point occlusion during angle
# changes (e.g. one wrist goes behind the subject, the other keeps
# tracking). The user picks either a single keypoint by name, one of
# these group names, or "auto" for whichever raw keypoint has the
# largest vertical variance across the clip.
KEYPOINT_GROUPS: dict[str, list[int]] = {
    "torso":     [5, 6, 11, 12],   # shoulders + hips
    "hips":      [11, 12],
    "shoulders": [5, 6],
    "wrists":    [9, 10],
    "elbows":    [7, 8],
    "knees":     [13, 14],
    "ankles":    [15, 16],
    "arms":      [7, 8, 9, 10],    # elbows + wrists
    "legs":      [13, 14, 15, 16], # knees + ankles
}


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
        detect_cuts = bool(pose.get("detect_scene_cuts", True))
        cut_threshold = max(0.05, min(0.9, float(pose.get("scene_cut_threshold", 0.35))))
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
        # Move the model to the target device ONCE, not per-predict —
        # per-call device kwarg triggers repeated H2D/D2H bookkeeping
        # that's most of the reason a 4070 Ti was only 1.3x faster than
        # CPU. Pinning it makes the actual GPU speedup show up.
        model = YOLO("yolov8n-pose.pt")
        model.to(device)
        # fp16 halves memory bandwidth and typically doubles throughput
        # on Ampere/Ada GPUs. YOLOv8n's accuracy hit at fp16 is
        # negligible. CPU can't do fp16 usefully, so keep it off there.
        use_half = device.startswith("cuda")
        # Batching amortizes CUDA launch overhead across many frames.
        # 32 is a sweet spot for YOLOv8n at 640 on modern GPUs; small
        # models are compute-light so throughput scales with batch size
        # until we're bandwidth-bound. Kept at 1 on CPU because larger
        # batches don't help there and cost memory.
        batch = 32 if device.startswith("cuda") else 1

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

        xy_series: list[np.ndarray | None] = []
        # Frame indices where a hard cut was detected. Includes 0 (start
        # of the clip is always a "cut" for normalization purposes) and
        # is used later to split xy_series into per-scene chunks so
        # each camera angle gets its own rolling range.
        cut_frames: list[int] = [0]
        prev_hist: np.ndarray | None = None
        # Last chosen person centroid — helps re-lock to the same person
        # after brief occlusions. Simple heuristic: nearest centroid wins.
        last_centroid: tuple[float, float] | None = None

        def flush(batch_frames: list) -> None:
            nonlocal last_centroid
            if not batch_frames:
                return
            # `quantize='fp16'` replaces the deprecated `half=True`
            # kwarg on newer ultralytics. Only meaningful on CUDA;
            # CPU fp16 is slower than fp32 in practice.
            kwargs = {"quantize": "fp16"} if use_half else {}
            results = model.predict(
                batch_frames, verbose=False, conf=confidence,
                imgsz=infer_w, **kwargs,
            )
            for res in results:
                person_kpts = _pick_person(res, last_centroid)
                if person_kpts is None:
                    xy_series.append(None)
                else:
                    xy_series.append(person_kpts)
                    torso = person_kpts[[5, 6, 11, 12], :]
                    cx = float(np.mean(torso[:, 0]))
                    cy = float(np.mean(torso[:, 1]))
                    last_centroid = (cx, cy)

        frame_buffer: list = []
        frame_idx = 0
        last_progress = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if scale < 1.0:
                    frame = cv2.resize(frame, (infer_w, infer_h), interpolation=cv2.INTER_AREA)

                # Scene-cut detection — cheap 8-bin-per-channel histogram
                # of the already-resized frame, compared with the previous
                # frame's via correlation. A big drop in correlation means
                # the visible pixels changed dramatically = hard cut. We
                # store the frame index; downstream signal processing uses
                # these to segment the funscript into per-scene chunks
                # with independent rolling ranges.
                if detect_cuts:
                    hist = cv2.calcHist(
                        [frame], [0, 1, 2], None, [8, 8, 8],
                        [0, 256, 0, 256, 0, 256],
                    )
                    cv2.normalize(hist, hist)
                    if prev_hist is not None:
                        correlation = float(cv2.compareHist(
                            prev_hist, hist, cv2.HISTCMP_CORREL,
                        ))
                        # correlation near 1.0 = similar frames; < threshold
                        # means the scene changed. Also require a minimum
                        # distance between cuts (0.5s) so a flashy strobe
                        # doesn't spam boundaries.
                        min_gap = int(fps * 0.5)
                        if correlation < (1.0 - cut_threshold) and \
                                (frame_idx - cut_frames[-1]) > min_gap:
                            cut_frames.append(frame_idx)
                    prev_hist = hist

                frame_buffer.append(frame)
                frame_idx += 1
                if len(frame_buffer) >= batch:
                    flush(frame_buffer)
                    frame_buffer = []
                    if frame_idx - last_progress >= 30:
                        progress_cb(min(0.9, 0.9 * frame_idx / total_frames))
                        last_progress = frame_idx
            # Drain the tail batch that didn't fill.
            flush(frame_buffer)
        finally:
            cap.release()

        n = len(xy_series)
        if n < 4:
            write_funscript(out_path, [{"at": 0, "pos": 50}])
            progress_cb(1.0)
            return

        # Resolve the tracked keypoint. Result is either:
        #  * a single index (0..16) for a raw keypoint,
        #  * a list of indices for a group (torso, wrists, etc.) whose
        #    per-frame position is the mean of visible member points.
        kp_target = _resolve_keypoint_target(keypoint, xy_series)

        # Extract the chosen coordinate per frame. Missing frames become
        # NaN; we linearly interpolate through the gaps so the smoothing
        # step has a continuous signal. When kp_target is a group, we
        # average across the group's keypoints — a single-point occlusion
        # (a wrist behind the subject during an angle change) doesn't
        # take out the whole frame.
        signal = np.full(n, np.nan, dtype=np.float64)
        for i, kpts in enumerate(xy_series):
            if kpts is None:
                continue
            if isinstance(kp_target, list):
                # Ignore (0, 0) placeholder points — YOLO uses those when
                # a keypoint has zero confidence, which would drag the
                # mean toward the frame origin.
                pts = np.asarray([kpts[k] for k in kp_target], dtype=np.float64)
                mask = (pts.sum(axis=1) > 0)
                if not mask.any():
                    continue
                pts = pts[mask]
                x, y = float(pts[:, 0].mean()), float(pts[:, 1].mean())
            else:
                x, y = float(kpts[kp_target][0]), float(kpts[kp_target][1])
                if x == 0 and y == 0:
                    continue
            if axis == "x":
                signal[i] = x
            elif axis == "magnitude":
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

        # Per-scene signal → actions. Each scene between adjacent
        # `cut_frames` boundaries is normalized independently so the
        # rolling range from one camera angle doesn't rescale another.
        scene_bounds = _scene_bounds_from_cuts(cut_frames, n)
        actions: list[dict] = []
        reversal_indices: list[int] = []
        for s_start, s_end in scene_bounds:
            if s_end - s_start < 4:
                continue
            scene_signal = signal[s_start:s_end]
            scene_actions, scene_reversals = _signal_to_actions(
                scene_signal, fps, invert=invert, time_offset_frames=s_start,
            )
            actions.extend(scene_actions)
            reversal_indices.extend(scene_reversals)

        if not actions:
            actions = [{"at": 0, "pos": 50}]

        # De-collide timestamps that adjacent-scene concatenation may
        # have produced when a scene boundary landed exactly between
        # two frames.
        actions.sort(key=lambda a: a["at"])
        for i in range(1, len(actions)):
            if actions[i]["at"] <= actions[i - 1]["at"]:
                actions[i]["at"] = actions[i - 1]["at"] + 1

        write_funscript(out_path, actions)

        if debug_out_path is not None:
            from app.processing.debug import render_pose_debug
            progress_cb(0.92)
            # Debug renderer wants a list of highlighted keypoint indices —
            # single-keypoint mode gets a one-item list so the drawing
            # code has one shape to reason about.
            highlight = kp_target if isinstance(kp_target, list) else [kp_target]
            render_pose_debug(
                source_video=video.path,
                out_path=debug_out_path,
                xy_series=xy_series,
                highlight_keypoints=highlight,
                axis=axis,
                scale=scale,
                reversal_frame_indices=reversal_indices,
                scene_cut_frames=cut_frames if detect_cuts else [],
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


def _resolve_keypoint_target(spec, xy_series):
    """Resolve the pose keypoint spec into either an int (single point)
    or a list of ints (group). Accepts:
      * int in [0, 17)                — that raw keypoint
      * "auto"                        — scan and pick the highest-std one
      * a KEYPOINT_NAMES entry        — that raw keypoint
      * a KEYPOINT_GROUPS key         — that group of keypoints
    Falls back to left_hip if nothing matches.
    """
    if isinstance(spec, int) and 0 <= spec < 17:
        return spec
    if isinstance(spec, str):
        if spec in KEYPOINT_GROUPS:
            return list(KEYPOINT_GROUPS[spec])
        if spec == "auto":
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


def _scene_bounds_from_cuts(cut_frames: list[int], n_frames: int) -> list[tuple[int, int]]:
    """Turn a list of cut frame indices into (start, end) pairs covering
    [0, n_frames). Always includes the final segment even when the last
    cut is followed by more frames."""
    if not cut_frames or cut_frames[0] != 0:
        cut_frames = [0] + list(cut_frames)
    bounds: list[tuple[int, int]] = []
    for i, start in enumerate(cut_frames):
        end = cut_frames[i + 1] if i + 1 < len(cut_frames) else n_frames
        if end > start:
            bounds.append((start, end))
    return bounds


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
    time_offset_frames: int = 0,
) -> tuple[list[dict], list[int]]:
    """Same shape/normalization/peak-detection pipeline zone mode uses.
    Kept local (rather than imported from zone.py) so pose mode is
    self-contained and easy to tune without leaking regressions into
    the older modes.

    `time_offset_frames` shifts the output timestamps/indices by that
    many source frames — the caller uses this to stitch per-scene
    results back into a single funscript with correct absolute times.
    """
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
        return [], []
    actions: list[dict] = []
    for i in indices:
        absolute_frame = i + time_offset_frames
        at_ms = int(round(absolute_frame / fps * 1000))
        pos = int(round(float(normalized[i])))
        actions.append({"at": at_ms, "pos": max(0, min(100, pos))})
    deduped: list[dict] = []
    for a in actions:
        if deduped and a["at"] <= deduped[-1]["at"]:
            a["at"] = deduped[-1]["at"] + 1
        deduped.append(a)
    # Return absolute frame indices for the debug renderer's flash cues.
    absolute_indices = [i + time_offset_frames for i in indices]
    return deduped, absolute_indices
