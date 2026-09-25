"""Neural beat tracker — CPJKU's BEAT This! (2024) via the beat_this
package. This is the current SOTA for beat tracking on public
benchmarks.

The tracker is a PyTorch transformer trained on ~700 hours of annotated
music. It handles tempo drift, syncopation, live/acoustic performances,
and heavily-mixed electronic tracks far better than any signal-
processing baseline, while running fast enough on CPU for
funscript-gen's use case (a 5-minute clip typically finishes in
10-30 seconds on modern desktop CPUs).

The model auto-downloads on first use (~30 MB) from CPJKU's public
storage to torch's hub cache; subsequent runs are instant.

We use `Audio2Frames` to get the raw model activations (one per
audio frame, ~50 Hz), then apply the `Postprocessor` ourselves to
extract discrete beat times and downbeat times. This lets us hand
the frame-level activation curve to the debug renderer as the beat-bar
novelty envelope — musically meaningful, showing where the model
actually saw beat probability, not just a signal-processing proxy.
"""
from __future__ import annotations

import numpy as np

# Model instantiation is heavy (~1-2s cold start) and completely stateless
# once loaded. Cache both the frame extractor and the postprocessor so a
# batch of jobs in the same process pays the load cost once.
_FRAMES = None
_POSTPROC: dict = {}
_FRAME_HZ = 50  # BEAT This emits 50 activation frames per second


def _get_frames_model():
    global _FRAMES
    if _FRAMES is not None:
        return _FRAMES
    from beat_this.inference import Audio2Frames
    _FRAMES = Audio2Frames(checkpoint_path="final0", device="cpu")
    return _FRAMES


def _get_postproc(dbn: bool):
    key = "dbn" if dbn else "minimal"
    if key in _POSTPROC:
        return _POSTPROC[key]
    from beat_this.inference import Postprocessor
    _POSTPROC[key] = Postprocessor(type=key, fps=_FRAME_HZ)
    return _POSTPROC[key]


def detect_beats_neural(
    pcm: np.ndarray,
    sample_rate: int,
    *,
    use_dbn: bool = False,
) -> tuple[list[int], list[int], np.ndarray, float]:
    """Run BEAT This! over the whole clip.

    Returns (beat_times_ms, downbeat_times_ms, novelty, novelty_hop_ms).
      * beat_times_ms:     every detected beat
      * downbeat_times_ms: subset of beats that BEAT This tagged as
                           downbeats (first beat of each measure)
      * novelty:           frame-level beat activations from the model
                           (0..1), one value per ~20 ms. Feeds the
                           beat bar's envelope so the debug overlay
                           shows what the MODEL saw, not a proxy.
      * novelty_hop_ms:    1000 / 50 Hz = 20 ms per novelty sample.
    """
    if pcm.size == 0:
        return [], [], np.zeros(0, dtype=np.float32), 1000.0 / _FRAME_HZ

    frames_model = _get_frames_model()
    postproc = _get_postproc(dbn=use_dbn)

    # Audio2Frames handles resampling internally and returns two 1-D
    # tensors of frame-level logits (beat / downbeat).
    beat_logits, downbeat_logits = frames_model(pcm.astype(np.float32), sample_rate)

    # Postprocessor turns logits + softmax into discrete time lists.
    beats_s, downbeats_s = postproc(beat_logits, downbeat_logits)
    beat_ms = [int(round(float(t) * 1000.0)) for t in beats_s]
    downbeat_ms = [int(round(float(t) * 1000.0)) for t in downbeats_s]

    # Frame activations → novelty curve for the beat bar envelope.
    # Sigmoid the logits and normalize so the debug renderer's fill-bar
    # math (which expects [0, 1]) is happy.
    import torch
    beat_probs = torch.sigmoid(beat_logits).cpu().numpy().astype(np.float32)
    if beat_probs.max() > 0:
        beat_probs = beat_probs / float(beat_probs.max())

    return beat_ms, downbeat_ms, beat_probs, 1000.0 / _FRAME_HZ


def detect_onsets_neural(
    pcm: np.ndarray,
    sample_rate: int,
    *,
    tightness: float = 100.0,
    hop_ms: float = 10.0,
) -> tuple[list[int], np.ndarray, float]:
    """Backwards-compat shim matching `audio_beats.detect_onsets`.

    Returns only beats + novelty (no downbeats). New code should call
    `detect_beats_neural` directly to get downbeats too.
    """
    _ = hop_ms  # unused — frame rate is fixed at 50 Hz by the model
    use_dbn = tightness >= 200
    beats, _, novelty, novelty_hop_ms = detect_beats_neural(
        pcm, sample_rate, use_dbn=use_dbn,
    )
    return beats, novelty, novelty_hop_ms
