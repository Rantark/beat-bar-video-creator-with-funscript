"""Learned beat tracker (librosa-based) as an alternative to the raw
spectral-flux onset detector in `audio_beats.detect_onsets`.

librosa's `beat.beat_track` uses onset envelope autocorrelation to
estimate tempo, then a dynamic-programming beat-picker that follows a
learned prior over musically-plausible sequences. It's significantly
more accurate on real music than raw spectral-flux peak-picking —
handles tempo changes, syncopation, and quiet passages far better —
while staying entirely local (no cloud calls, no external API keys).

We keep the same return contract as `audio_beats.detect_onsets` so
`AudioProcessor` can pick between the two at runtime with just a flag,
and everything downstream (regularization, patterns, editor UI) works
untouched.

Trade-offs:
  * Slower (~2-3x) than spectral flux for a 5-minute clip.
  * First run on a machine cold-loads llvmlite + numba; subsequent
    runs are much faster.
  * Depends on librosa (pulled in via requirements.txt when installed).
"""
from __future__ import annotations

import numpy as np


def detect_onsets_neural(
    pcm: np.ndarray,
    sample_rate: int,
    *,
    tightness: float = 100.0,
    hop_ms: float = 10.0,
) -> tuple[list[int], np.ndarray, float]:
    """Drop-in replacement for `audio_beats.detect_onsets`.

    Returns (beat_times_ms, novelty, novelty_hop_ms) so the beat-bar
    debug renderer can still plot activity underneath the beat ticks.

    `tightness` is librosa's beat-tracker rigidity — higher = the picker
    sticks harder to the estimated tempo, useful when a song has a
    steady beat under a busy surface. Default matches librosa's own.
    """
    if pcm.size == 0:
        return [], np.zeros(0, dtype=np.float32), float(hop_ms)

    # Import here so a user who never enables the neural tracker never
    # pays the librosa/numba import cost.
    import librosa

    hop_length = max(1, int(round(sample_rate * hop_ms / 1000.0)))

    # Onset envelope (novelty curve) is what both the beat tracker and
    # our debug renderer want. Computing it here once means we don't
    # duplicate work inside beat_track.
    onset_env = librosa.onset.onset_strength(
        y=pcm, sr=sample_rate, hop_length=hop_length,
    )

    tempo_est, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env,
        sr=sample_rate,
        hop_length=hop_length,
        tightness=float(tightness),
    )
    _ = tempo_est  # unused — the section regularizer estimates tempo per section anyway

    beat_times = librosa.frames_to_time(
        beat_frames, sr=sample_rate, hop_length=hop_length,
    )
    onset_ms = [int(round(float(t) * 1000.0)) for t in beat_times]

    # Normalize novelty to [0, 1] like the spectral-flux path so the
    # debug renderer's fill-bar math is compatible.
    novelty = np.asarray(onset_env, dtype=np.float32)
    if novelty.max() > 0:
        novelty = novelty / novelty.max()

    return onset_ms, novelty, float(hop_ms)
