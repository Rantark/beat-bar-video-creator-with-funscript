"""Neural beat tracker — CPJKU's BEAT This! (2024) via the beat_this
package. This is the current SOTA for beat tracking on public
benchmarks (F1 ~89% on GTZAN vs madmom's ~85%, librosa's ~72%).

The tracker is a PyTorch transformer trained on ~700 hours of annotated
music. It handles tempo drift, syncopation, live/acoustic performances,
and heavily-mixed electronic tracks far better than any signal-
processing baseline, while running fast enough on CPU for
funscript-gen's use case (a 5-minute clip typically finishes in
10-30 seconds on modern desktop CPUs).

The model auto-downloads on first use (~30 MB) from CPJKU's public
storage to torch's hub cache; subsequent runs are instant.

We keep the same (beat_times_ms, novelty, novelty_hop_ms) return
contract as `audio_beats.detect_onsets` so `AudioProcessor` can pick
between the two at runtime with just a flag, and everything downstream
(regularization, patterns, editor UI) works untouched. Since BEAT This
doesn't expose an onset envelope of its own, we still compute a coarse
spectral-flux novelty for the debug renderer's bar visualization.
"""
from __future__ import annotations

import numpy as np


# The model is heavy to instantiate (~1-2s cold start) and completely
# stateless once loaded. Cache the instance so a batch of jobs in the
# same process pays that cost once, not per-job.
_TRACKER = None


def _get_tracker(dbn: bool):
    global _TRACKER
    if _TRACKER is not None and _TRACKER[1] == dbn:
        return _TRACKER[0]
    from beat_this.inference import Audio2Beats
    tracker = Audio2Beats(checkpoint_path="final0", device="cpu", dbn=dbn)
    _TRACKER = (tracker, dbn)
    return tracker


def _cheap_novelty(pcm: np.ndarray, sr: int, hop_ms: float) -> np.ndarray:
    """Small spectral-flux novelty curve for the debug bar visualization.
    BEAT This doesn't expose one; we don't need musical accuracy here
    since it's only for the visual scrolling bar underneath the ticks."""
    hop = max(1, int(round(sr * hop_ms / 1000.0)))
    n_fft = 2048
    if pcm.size < n_fft * 2:
        return np.zeros(0, dtype=np.float32)
    # Frame + STFT magnitude
    from scipy.signal import stft
    _, _, Zxx = stft(pcm, fs=sr, nperseg=n_fft, noverlap=max(0, n_fft - hop),
                     boundary=None)
    mag = np.log1p(np.abs(Zxx) * 100.0)
    diff = np.diff(mag, axis=1)
    diff = np.maximum(diff, 0.0)
    flux = np.concatenate([[0.0], diff.sum(axis=0)])
    if flux.max() > 0:
        flux = flux / flux.max()
    return flux.astype(np.float32)


def detect_onsets_neural(
    pcm: np.ndarray,
    sample_rate: int,
    *,
    tightness: float = 100.0,
    hop_ms: float = 10.0,
) -> tuple[list[int], np.ndarray, float]:
    """Drop-in replacement for `audio_beats.detect_onsets`.

    Returns (beat_times_ms, novelty, novelty_hop_ms). `tightness` is
    kept in the signature for API parity with the librosa-era code but
    is unused here — BEAT This! has its own learned tempo prior and
    doesn't expose a rigidity knob. The DBN post-processor (an HMM
    over the raw model output) is enabled when tightness >= 200; this
    is a rough proxy for "prefer a steadier tempo, trade some accuracy
    on live/drifting material."
    """
    _ = tightness  # documented above; retained for signature parity
    if pcm.size == 0:
        return [], np.zeros(0, dtype=np.float32), float(hop_ms)

    # DBN toggle: on for high tightness (steady-tempo material), off
    # otherwise (BEAT This's raw output actually beats DBN on GTZAN).
    use_dbn = tightness >= 200
    tracker = _get_tracker(dbn=use_dbn)

    # BEAT This resamples internally to 22.05 kHz mono; we pass whatever
    # we have and let it handle the resample.
    beat_times, _downbeat_times = tracker(pcm.astype(np.float32), sample_rate)
    onset_ms = [int(round(float(t) * 1000.0)) for t in beat_times]

    novelty = _cheap_novelty(pcm, sample_rate, hop_ms)
    return onset_ms, novelty, float(hop_ms)
