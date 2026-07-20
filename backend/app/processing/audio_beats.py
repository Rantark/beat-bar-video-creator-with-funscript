"""Audio-driven beat detection.

Extracts the audio from a video via ffmpeg (mono, 22 kHz), runs a
spectral-flux onset detector on it, and returns beat timestamps in ms.
Everything downstream (section detection, funscript shape, smoothing)
is handled by `beat_actions.beats_to_actions()` — this module is the
audio analogue of the color-signal work marker/line do on frames.

No librosa dependency; scipy + numpy is enough for a solid MVP.
"""
from __future__ import annotations

import random
import struct
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks, stft

from app.config import settings

SECTION_STEP_MS = 5000  # every section length is a multiple of this


def extract_audio_pcm(video_path: Path, sample_rate: int = 22050) -> np.ndarray:
    """Decode the source video's first audio track to mono float32 PCM.

    Returns an empty array when the video has no audio track — the
    caller should treat that as "no beats" rather than crash.
    """
    cmd = [
        settings.ffmpeg_path,
        "-nostdin",
        "-loglevel", "error",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-f", "f32le",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return np.zeros(0, dtype=np.float32)
    n = len(proc.stdout) // 4
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(proc.stdout[: n * 4], dtype=np.float32).copy()


def detect_onsets(
    pcm: np.ndarray,
    sample_rate: int,
    *,
    sensitivity: float = 0.5,
    min_gap_ms: int = 120,
    low_hz: float = 60.0,
    high_hz: float = 8000.0,
) -> tuple[list[int], np.ndarray, float]:
    """Spectral-flux onset detector.

    Returns (onset_times_ms, novelty_curve, novelty_hop_ms). The novelty
    curve is returned so the debug renderer can plot it in the beat bar.
    """
    if pcm.size == 0:
        return [], np.zeros(0, dtype=np.float32), 10.0

    hop_ms = 10
    n_fft = 2048
    hop = max(1, int(sample_rate * hop_ms / 1000))
    noverlap = max(0, n_fft - hop)
    freqs, times, Zxx = stft(
        pcm, fs=sample_rate, nperseg=n_fft, noverlap=noverlap, boundary=None,
    )
    mag = np.abs(Zxx).astype(np.float64)
    if mag.shape[1] < 2:
        return [], np.zeros(0, dtype=np.float32), float(hop_ms)

    # Restrict to the useful band. Kick drums and bass live below ~200 Hz;
    # snares and rhythmic accents are 200–8k. Vocals lower the S/N so we
    # leave a knob for the user to squeeze the range.
    band = (freqs >= low_hz) & (freqs <= high_hz)
    if band.any():
        mag = mag[band, :]

    # Log-compressed magnitude — perceptually closer to how a listener
    # hears loudness, and makes soft accents visible next to loud ones.
    mag = np.log1p(mag * 100.0)

    # Spectral flux = sum over frequency of positive frame-to-frame diff.
    diff = np.diff(mag, axis=1)
    diff = np.maximum(diff, 0.0)
    flux = diff.sum(axis=0)
    # Pad so `flux[i]` corresponds to `times[i]`.
    flux = np.concatenate([[0.0], flux])

    # Adaptive baseline — subtract a short moving mean so a sustained
    # loud passage doesn't get one giant onset at the start and nothing
    # after. Window ~250 ms.
    win = max(3, int(250 / hop_ms))
    kernel = np.ones(win) / win
    baseline = np.convolve(flux, kernel, mode="same")
    novelty = flux - baseline
    novelty = np.maximum(novelty, 0.0)

    if novelty.max() > 0:
        novelty = novelty / novelty.max()

    # Sensitivity 0..1 → threshold 0.35..0.05. Default 0.5 → 0.20.
    s = max(0.0, min(1.0, float(sensitivity)))
    threshold = 0.35 - 0.30 * s
    min_gap_frames = max(1, int(min_gap_ms / hop_ms))
    peaks, _ = find_peaks(novelty, height=threshold, distance=min_gap_frames)
    onset_ms = [int(round(float(times[p]) * 1000)) for p in peaks]
    return onset_ms, novelty.astype(np.float32), float(hop_ms)


def plan_sections(
    video_duration_ms: int,
    *,
    section_min_ms: int,
    section_target_ms: int,
    section_max_ms: int,
    fluctuation: float,
    seed: int = 0,
) -> list[tuple[int, int]]:
    """Walk the timeline picking section lengths in `SECTION_STEP_MS`
    multiples, biased around `section_target_ms` with `fluctuation`
    controlling the spread.

    fluctuation=0 → every section is exactly `section_target_ms` (snapped
    to a 5 s multiple). fluctuation=1 → uniform over
    [section_min_ms, section_max_ms]. In between scales linearly.

    Returns a list of (start_ms, end_ms) pairs covering [0, duration].
    """
    step = SECTION_STEP_MS
    lo = max(step, (max(0, section_min_ms) // step) * step)
    hi = max(lo, (max(section_max_ms, lo) // step) * step)
    target = max(lo, min(hi, section_target_ms))
    # Snap target to nearest step, staying inside [lo, hi].
    target = round(target / step) * step
    target = max(lo, min(hi, target))
    f = max(0.0, min(1.0, fluctuation))

    # Symmetric spread around target so fluctuation=1 covers the full
    # range regardless of where target sits. Small side of (target-lo)
    # and (hi-target) caps how far we can swing on the tighter side.
    half_span = min(target - lo, hi - target)
    spread = int(f * half_span)
    # Round spread down to a step multiple so all draws stay on-grid.
    spread = (spread // step) * step

    rng = random.Random(seed)
    out: list[tuple[int, int]] = []
    t = 0
    while t < video_duration_ms:
        length = target if spread == 0 else target + rng.randint(-spread // step, spread // step) * step
        length = max(lo, min(hi, length))
        end = min(video_duration_ms, t + length)
        # Avoid a runt trailing section — if the leftover is shorter
        # than lo, absorb it into the previous section instead.
        if video_duration_ms - end < lo and out:
            prev_start, _ = out[-1]
            out[-1] = (prev_start, video_duration_ms)
            return out
        out.append((t, end))
        t = end
    return out


def _pick_pattern_index_for_period(
    patterns: list[list[bool]], period_ms: int, rng: random.Random,
) -> int:
    """Weighted random pick index into `patterns`. Dense patterns win
    on short-period (fast) sections; sparse patterns win on long-period
    (slow) sections. See doc in the caller."""
    speed = 1.0 - (max(200, min(1500, period_ms)) - 200) / 1300.0
    weights: list[float] = []
    for p in patterns:
        density = sum(1 for x in p if x) / len(p)
        distance = abs(density - speed)
        weights.append(max(0.05, 1.0 - distance * 2.0))
    total = sum(weights)
    if total <= 0:
        return rng.randint(0, len(patterns) - 1)
    pick = rng.random() * total
    cumsum = 0.0
    for i, w in enumerate(weights):
        cumsum += w
        if cumsum >= pick:
            return i
    return len(patterns) - 1


def regularize_beats(
    onset_ms: list[int],
    novelty: np.ndarray,
    novelty_hop_ms: float,
    video_duration_ms: int,
    *,
    section_min_ms: int = 10000,
    section_target_ms: int = 20000,
    section_max_ms: int = 30000,
    section_fluctuation: float = 0.0,
    pattern_variety: float = 0.0,
    patterns: list[list[bool]] | None = None,
    min_onsets_per_section: int = 4,
) -> tuple[list[int], list[dict]]:
    """Quantize raw onsets to a per-section steady tempo.

    Splits the timeline into windows sized in 5-second multiples between
    `section_min_ms` and `section_max_ms`, biased around
    `section_target_ms`. `section_fluctuation` (0..1) controls how much
    length varies from section to section — 0 = every section is the
    target length, 1 = full random spread across the range.

    For each window: pick the dominant inter-onset interval as the beat
    period, emit a regular grid at that period phase-aligned to the
    first real onset in the window. Windows with zero onsets emit
    nothing so the downstream idle animation fills them; windows with
    a few onsets pass them through raw (not enough to lock tempo).
    """
    _ = novelty, novelty_hop_ms  # kept in the signature for API stability
    if not onset_ms or video_duration_ms <= 0:
        return list(onset_ms), []

    # Drop empty patterns (all-off) — they'd contribute no beats and
    # would produce a dead section if picked.
    usable_patterns: list[list[bool]] = [
        p for p in (patterns or []) if any(p) and len(p) >= 2
    ]

    # Deterministic seed so re-runs on the same audio produce the same
    # section layout — makes it easier for the user to iterate on other
    # knobs without the underlying section grid shifting under them.
    seed = hash(tuple(onset_ms[:32])) & 0x7FFFFFFF
    sections = plan_sections(
        video_duration_ms,
        section_min_ms=section_min_ms,
        section_target_ms=section_target_ms,
        section_max_ms=section_max_ms,
        fluctuation=section_fluctuation,
        seed=seed,
    )
    # Separate RNG for the per-section pattern roll so it's independent
    # of the section-planner draws (changing pattern_variety shouldn't
    # move section boundaries around).
    pattern_rng = random.Random(seed ^ 0xA5A5A5A5)
    out: list[int] = []
    section_meta: list[dict] = []

    for s_start, s_end in sections:
        section_onsets = [t for t in onset_ms if s_start <= t < s_end]
        if not section_onsets:
            # Truly silent section — leave empty so idle animation fills it.
            continue
        if len(section_onsets) < min_onsets_per_section:
            # A few onsets, not enough to lock tempo — pass them through
            # raw rather than inventing a grid from noise.
            out.extend(section_onsets)
            continue

        # Inter-onset interval histogram, restricted to a musical range
        # (200 ms = 300 BPM, 1500 ms = 40 BPM). Anything outside that is
        # either double-counted onsets or a very slow drone.
        iois = np.diff(section_onsets)
        iois = iois[(iois >= 200) & (iois <= 1500)]
        if iois.size < 2:
            out.extend(section_onsets)
            continue

        bins = np.arange(200, 1501, 25)
        hist, edges = np.histogram(iois, bins=bins)
        peak = int(np.argmax(hist))
        # Weighted center over the peak bin plus its immediate neighbors
        # so small quantization noise doesn't snap us to a rigid 25 ms grid.
        lo = max(0, peak - 1)
        hi = min(hist.size, peak + 2)
        weights = hist[lo:hi].astype(np.float64)
        centers = (edges[lo:hi] + edges[lo + 1:hi + 1]) / 2.0
        if weights.sum() > 0:
            period_ms = int(round(float((weights * centers).sum() / weights.sum())))
        else:
            period_ms = int(round(float(edges[peak] + 12)))
        period_ms = max(200, min(1500, period_ms))

        # Pattern variety — with probability `pattern_variety`, shift
        # this section to a musically-related subdivision of the base
        # period (half-time = 2x period, double-time = 0.5x). Rolled
        # per section with a dedicated RNG so re-runs are stable and
        # the section boundaries stay put when you tune the knob.
        pv = max(0.0, min(1.0, pattern_variety))
        if pv > 0 and pattern_rng.random() < pv:
            # Weighted: base is always allowed, half/double gate on how
            # far the shifted period would land inside the musical band.
            choices: list[float] = [1.0]
            if period_ms * 2 <= 1500:
                choices.append(2.0)
            if period_ms // 2 >= 200:
                choices.append(0.5)
            factor = pattern_rng.choice(choices)
            period_ms = max(200, min(1500, int(round(period_ms * factor))))

        # Phase: anchor on the first real onset in the section so the
        # grid stays synced with the music instead of drifting off it.
        anchor = section_onsets[0]
        # Backfill grid points before the anchor if the section starts
        # earlier than the first onset (short lead-in).
        first_grid = anchor
        while first_grid - period_ms >= s_start:
            first_grid -= period_ms

        pattern_idx: int | None = None
        if usable_patterns:
            # Pick a pattern per section, weighting toward patterns
            # whose density matches the section's speed.
            pattern_idx = _pick_pattern_index_for_period(
                usable_patterns, period_ms, pattern_rng,
            )
            pattern = usable_patterns[pattern_idx]
            slot = 0
            t = first_grid
            while t < s_end:
                if pattern[slot % len(pattern)]:
                    out.append(int(t))
                t += period_ms
                slot += 1
        else:
            t = first_grid
            while t < s_end:
                out.append(int(t))
                t += period_ms

        section_meta.append({
            "start_ms": int(s_start),
            "end_ms": int(s_end),
            "period_ms": int(period_ms),
            "anchor_ms": int(first_grid),
            "pattern_index": pattern_idx,
        })

    out.sort()
    # Dedup near-duplicates (adjacent sections whose grids meet at a
    # boundary can land within a few ms of each other).
    deduped: list[int] = []
    for t in out:
        if deduped and t - deduped[-1] < 100:
            continue
        deduped.append(t)
    return deduped, section_meta


def probe_audio_present(video_path: Path) -> bool:
    """Cheap ffprobe check for whether the source has any audio stream."""
    cmd = [
        settings.ffprobe_path,
        "-loglevel", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        str(video_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and "audio" in proc.stdout


# Not used at runtime, but kept so tests / debug tooling can round-trip
# raw PCM to a wav file for listening.
def write_wav(pcm: np.ndarray, sample_rate: int, out_path: Path) -> None:
    n = pcm.size
    with open(out_path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + n * 4))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 3, 1, sample_rate, sample_rate * 4, 4, 32))
        f.write(b"data")
        f.write(struct.pack("<I", n * 4))
        f.write(pcm.astype(np.float32).tobytes())
