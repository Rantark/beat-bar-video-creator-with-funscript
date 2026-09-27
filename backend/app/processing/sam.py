"""Object-tracking funscript generation via SAM 2 (Segment Anything 2).

The user picks a frame + click point on the "thing" they want tracked;
SAM 2 propagates a segmentation mask of that specific object through
the entire video. The mask's centroid becomes the tracked position
signal, which flows through the same per-scene normalization pipeline
pose mode uses.

Advantages over pose:
- Not limited to anatomy — can track a toy, a hand, a UI element,
  anything that's visually consistent.
- Handles color changes, rotation, scale, and partial occlusion better
  than classical template matching (marker mode's template feature).
- One-click prompt in a single frame is enough for the whole clip.

Limitations we handle explicitly:
- Hard scene cuts confuse SAM 2 (no concept of "the thing continues").
  When `detect_scene_cuts=True`, we detect cuts via histogram delta
  and split the funscript into per-scene chunks with independent
  rolling ranges — same fix pose uses for angle changes.
- Long occlusion can lose the object. We interpolate through short
  gaps like pose does.

Speed on modern GPU:
- SAM 2.1 hiera tiny at 512x512 does ~30-60 fps on a 4070 Ti.
- CPU inference is slow enough (~1-2 fps) that we default to auto
  device selection like the other neural modes.
"""
from __future__ import annotations

import urllib.request
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

# One-line-per-variant catalog. Weights are hosted by Meta on their
# public S3 bucket. Downloaded lazily to torch's hub cache the first
# time this mode runs.
_MODEL_VARIANTS = {
    "tiny": (
        "sam2.1_hiera_t.yaml",
        "sam2.1_hiera_tiny.pt",
        "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt",
    ),
    "small": (
        "sam2.1_hiera_s.yaml",
        "sam2.1_hiera_small.pt",
        "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt",
    ),
    "base+": (
        "sam2.1_hiera_b+.yaml",
        "sam2.1_hiera_base_plus.pt",
        "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt",
    ),
    "large": (
        "sam2.1_hiera_l.yaml",
        "sam2.1_hiera_large.pt",
        "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt",
    ),
}


def _ensure_checkpoint(url: str, name: str) -> Path:
    """Auto-download the SAM 2 weights to torch's hub cache on first use."""
    import torch
    cache_dir = Path(torch.hub.get_dir()) / "checkpoints"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dst = cache_dir / name
    if not dst.exists():
        print(f"[sam] downloading {name} from {url}", flush=True)
        urllib.request.urlretrieve(url, dst)
        print(f"[sam] saved to {dst}", flush=True)
    return dst


class SamProcessor:
    def run(
        self,
        video: VideoInfo,
        params: dict,
        out_path: Path,
        progress_cb: Callable[[float], None],
        debug_out_path: Path | None = None,
    ) -> None:
        sam_params = params.get("sam") or {}
        click_time_ms = int(sam_params.get("click_time_ms", 0))
        click_x_norm = float(sam_params.get("click_x", 0.5))
        click_y_norm = float(sam_params.get("click_y", 0.5))
        axis = sam_params.get("axis", "y")
        invert = bool(sam_params.get("invert", False))
        model_size = sam_params.get("model_size", "tiny")
        if model_size not in _MODEL_VARIANTS:
            model_size = "tiny"
        detect_cuts = bool(sam_params.get("detect_scene_cuts", True))
        cut_threshold = max(0.05, min(0.9, float(sam_params.get("scene_cut_threshold", 0.35))))
        device, device_note = resolve_device(sam_params.get("device"))
        if device_note:
            print(f"[sam] {device_note}", flush=True)

        try:
            from sam2.build_sam import build_sam2_video_predictor
        except ImportError as exc:
            raise RuntimeError(
                "Object mode requires the sam2 package — install with "
                "`pip install sam2` in the backend venv."
            ) from exc

        # Download the tiny model if this is the first Object job.
        cfg_name, ckpt_name, ckpt_url = _MODEL_VARIANTS[model_size]
        ckpt_path = _ensure_checkpoint(ckpt_url, ckpt_name)

        # Build the video predictor pinned to the target device. SAM 2's
        # hydra-driven builder wants the config filename (without the
        # configs/ prefix); it looks it up on the sam2 package's config
        # search path automatically.
        predictor = build_sam2_video_predictor(
            f"configs/sam2.1/{cfg_name}",
            ckpt_path=str(ckpt_path),
            device=device,
        )

        # Independent pass with cv2 to detect scene cuts. SAM 2 loads
        # frames internally with its own resize, so we don't get to
        # inspect them from inside its predictor. Cheap extra decode.
        fps = video.fps if video.fps > 0 else 30.0
        cut_frames: list[int] = [0]
        if detect_cuts:
            cut_frames = _detect_scene_cuts(
                video.path, threshold=cut_threshold, min_gap_s=0.5,
            )
            print(f"[sam] {len(cut_frames)} scene(s) detected", flush=True)

        progress_cb(0.1)

        # Run SAM 2 propagation. init_state loads all frames onto the
        # target device (or offloads to CPU when GPU VRAM is tight).
        import torch
        with torch.inference_mode():
            state = predictor.init_state(
                str(video.path),
                offload_video_to_cpu=(device == "cpu"),
            )

            # Prompt: single positive click at the user's chosen frame.
            # SAM 2 wants pixel coords in the ORIGINAL video resolution,
            # which is what we get by de-normalizing.
            click_frame = int(round(click_time_ms / 1000.0 * fps))
            click_frame = max(0, min(state["num_frames"] - 1, click_frame))
            click_px = np.array(
                [[click_x_norm * video.width, click_y_norm * video.height]],
                dtype=np.float32,
            )
            labels = np.array([1], dtype=np.int32)  # 1 = positive click
            predictor.add_new_points_or_box(
                inference_state=state,
                frame_idx=click_frame,
                obj_id=1,
                points=click_px,
                labels=labels,
            )
            progress_cb(0.15)

            # Propagate through the whole video. SAM 2 automatically
            # runs both forward from the click frame AND backward to
            # cover frames earlier in the clip when needed.
            n_frames = int(state["num_frames"])
            centroids: list[tuple[float, float] | None] = [None] * n_frames
            processed = 0
            for frame_idx, obj_ids, mask_logits in predictor.propagate_in_video(state):
                # obj_ids and mask_logits are lists — we only added one
                # object so take index 0. Mask logits are probability
                # maps; > 0 threshold picks foreground.
                if len(obj_ids) == 0:
                    processed += 1
                    continue
                mask = (mask_logits[0] > 0.0).squeeze().cpu().numpy()
                if mask.any():
                    ys, xs = np.where(mask)
                    centroids[frame_idx] = (float(xs.mean()), float(ys.mean()))
                processed += 1
                if processed % 30 == 0:
                    progress_cb(min(0.9, 0.15 + 0.75 * (processed / n_frames)))

        progress_cb(0.9)

        # Build the signal from centroids. Missing frames → NaN → linear
        # interpolation, same as pose mode.
        signal = np.full(n_frames, np.nan, dtype=np.float64)
        for i, c in enumerate(centroids):
            if c is None:
                continue
            x, y = c
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

        # Per-scene normalization — one camera angle can't rescale
        # another. Same logic pose uses.
        scene_bounds = _scene_bounds_from_cuts(cut_frames, n_frames)
        actions: list[dict] = []
        for s_start, s_end in scene_bounds:
            if s_end - s_start < 4:
                continue
            scene_actions, _ = _signal_to_actions(
                signal[s_start:s_end], fps, invert=invert,
                time_offset_frames=s_start,
            )
            actions.extend(scene_actions)

        if not actions:
            actions = [{"at": 0, "pos": 50}]
        actions.sort(key=lambda a: a["at"])
        for i in range(1, len(actions)):
            if actions[i]["at"] <= actions[i - 1]["at"]:
                actions[i]["at"] = actions[i - 1]["at"] + 1

        write_funscript(out_path, actions)

        if debug_out_path is not None:
            from app.processing.debug import render_sam_debug
            progress_cb(0.95)
            render_sam_debug(
                source_video=video.path,
                out_path=debug_out_path,
                centroids=centroids,
                scene_cut_frames=cut_frames if detect_cuts else [],
            )
        progress_cb(1.0)


# --- Helpers reused / adapted from pose.py ---------------------------------


def _detect_scene_cuts(
    video_path: Path, threshold: float, min_gap_s: float,
) -> list[int]:
    """Second-pass ffmpeg-free cut detection using cv2 histograms."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return [0]
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    min_gap = int(fps * min_gap_s)
    cuts = [0]
    prev_hist = None
    idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            # Downscale before histogram to speed things up
            if frame.shape[0] > 360:
                frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
            hist = cv2.calcHist(
                [frame], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256],
            )
            cv2.normalize(hist, hist)
            if prev_hist is not None:
                corr = float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL))
                if corr < (1.0 - threshold) and (idx - cuts[-1]) > min_gap:
                    cuts.append(idx)
            prev_hist = hist
            idx += 1
    finally:
        cap.release()
    return cuts


def _scene_bounds_from_cuts(cut_frames: list[int], n_frames: int) -> list[tuple[int, int]]:
    if not cut_frames or cut_frames[0] != 0:
        cut_frames = [0] + list(cut_frames)
    bounds: list[tuple[int, int]] = []
    for i, start in enumerate(cut_frames):
        end = cut_frames[i + 1] if i + 1 < len(cut_frames) else n_frames
        if end > start:
            bounds.append((start, end))
    return bounds


def _fill_nans(arr: np.ndarray) -> np.ndarray | None:
    mask = ~np.isnan(arr)
    if not mask.any():
        return None
    idx = np.arange(len(arr))
    return np.interp(idx, idx[mask], arr[mask])


def _signal_to_actions(
    positions: np.ndarray, fps: float, *, invert: bool = False,
    time_offset_frames: int = 0,
) -> tuple[list[dict], list[int]]:
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
        return [], []
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
    absolute_indices = [i + time_offset_frames for i in indices]
    return deduped, absolute_indices
