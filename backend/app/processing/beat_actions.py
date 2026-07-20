"""Shared pipeline: beat timestamps → funscript actions.

Both MarkerProcessor and LineProcessor produce a list of beat timestamps
(color peaks and line crossings, respectively). Everything downstream of
that — section detection, per-section amplitude, motion smoothing, idle
animation, dedup — is identical for both.

The only public function you normally call is `beats_to_actions()`. The
smaller helpers are exposed so the debug renderer or tests can reach in.
"""
from __future__ import annotations

import random
import statistics

from app.config import settings


def beats_to_actions(
    beats_ms: list[int],
    video_duration_ms: int,
    *,
    max_up: float = 100.0,
    max_down: float = 0.0,
    max_up_fast: float | None = None,
    max_down_fast: float | None = None,
    variety_amount: float = 0.0,
    idle_enabled: bool = True,
    motion_smoothing: int = 2,
) -> list[dict]:
    """Emit a funscript action list from a beat-timestamp list.

    Handles:
      * Grouping consecutive same-tempo beats into rhythmic *sections*
        so every stroke in a section shares one (up, down) amplitude.
      * Per-section variety — random sub-envelope inside the tempo target,
        seeded deterministically from the beat pattern.
      * Smoothstep motion between reversals so the toy accelerates
        gradually instead of slam-stopping at every extreme.
      * Idle oscillation during silent gaps.
    """
    if max_up_fast is None:
        max_up_fast = max_up
    if max_down_fast is None:
        max_down_fast = max_down
    # Enforce max_down ≤ max_down_fast ≤ max_up_fast ≤ max_up.
    max_up = max(0.0, min(100.0, max_up))
    max_down = max(0.0, min(100.0, max_down))
    if max_down > max_up:
        max_down, max_up = max_up, max_down
    max_up_fast = max(max_down, min(max_up, max_up_fast))
    max_down_fast = max(max_down, min(max_up_fast, max_down_fast))

    if not beats_ms:
        idle = emit_idle(0, video_duration_ms, idle_enabled)
        return idle if idle else [{"at": 0, "pos": int(round((max_up + max_down) / 2))}]

    sections = detect_sections(beats_ms)
    rng = random.Random(hash(tuple(beats_ms)))

    # Compute each section's (up, down), then flatten to per-beat records
    # so downstream code walks all beats in one pass regardless of which
    # section they belong to. section_idx lets us tell same-section pairs
    # apart from inter-section pairs when deciding the transition shape.
    beat_recs: list[tuple[int, int, int, int]] = []  # (t, s_up, s_down, sec_idx)
    for sec_idx, section in enumerate(sections):
        if len(section) >= 2:
            intervals = [section[i + 1] - section[i] for i in range(len(section) - 1)]
            median_interval = int(statistics.median(intervals))
        else:
            median_interval = 1000
        tt = interval_t(median_interval)
        base_up = max_up_fast + tt * (max_up - max_up_fast)
        base_down = max_down_fast + tt * (max_down - max_down_fast)
        s_up_f, s_down_f = apply_variety(base_up, base_down, variety_amount, rng)
        s_up = int(round(s_up_f))
        s_down = int(round(s_down_f))
        for t_beat in section:
            beat_recs.append((t_beat, s_up, s_down, sec_idx))

    actions: list[dict] = []
    first_t, first_up, first_down, _ = beat_recs[0]

    # Pre-first-beat gap: idle if long + enabled, otherwise start at the
    # first section's up so the toy has somewhere to descend from.
    if first_t > 0:
        if first_t >= settings.marker_idle_gap_threshold_ms and idle_enabled:
            actions.extend(emit_idle(0, first_t, idle_enabled))
        else:
            actions.append({"at": 0, "pos": first_up})

    actions.append({"at": first_t, "pos": first_down})

    # Iterate consecutive beat pairs. Every pair — including across
    # section boundaries — gets EITHER idle (long pause + idle enabled)
    # OR a midpoint upstroke. The old behavior only emitted midpoints
    # WITHIN a section, so short inter-section pauses left the toy
    # stuck at pos=0 the whole gap.
    for i in range(len(beat_recs) - 1):
        t1, up1, dn1, sec1 = beat_recs[i]
        t2, up2, dn2, sec2 = beat_recs[i + 1]
        gap = t2 - t1
        same_section = sec1 == sec2

        idle_here = (
            not same_section
            and idle_enabled
            and gap >= settings.marker_idle_gap_threshold_ms
        )
        if idle_here:
            actions.extend(emit_idle(t1, t2, idle_enabled))
        else:
            mid = (t1 + t2) // 2
            if same_section:
                up_pos = up1  # matches within-section behavior
            else:
                # Inter-section transition. Amplitude scales with the
                # gap length via the same fast→slow interpolation used
                # for the section shape — a short pause gets a modest
                # recovery upstroke, a longer pause gets closer to the
                # full max_up peak.
                tt = interval_t(gap)
                up_pos = int(round(max_up_fast + tt * (max_up - max_up_fast)))
            if mid > t1:
                actions.extend(smooth_between(
                    t1, mid, dn1, up_pos, motion_smoothing,
                ))
                actions.append({"at": mid, "pos": up_pos})
                actions.extend(smooth_between(
                    mid, t2, up_pos, dn2, motion_smoothing,
                ))
        actions.append({"at": t2, "pos": dn2})

    last_t = beat_recs[-1][0]
    if (
        idle_enabled
        and video_duration_ms - last_t >= settings.marker_idle_gap_threshold_ms
    ):
        actions.extend(emit_idle(last_t, video_duration_ms, idle_enabled))

    return dedupe(actions)


def interval_t(interval_ms: int) -> float:
    """Fast-slow interpolation coefficient in [0, 1]."""
    fast_ms = settings.marker_fast_interval_ms
    slow_ms = settings.marker_slow_interval_ms
    span = max(1, slow_ms - fast_ms)
    return max(0.0, min(1.0, (interval_ms - fast_ms) / span))


def detect_sections(beats_ms: list[int]) -> list[list[int]]:
    """Group consecutive beats into runs of similar tempo.

    Two consecutive intervals within TEMPO_TOLERANCE (as a fraction of
    the running interval) stay in the same section. A larger jump starts
    a new one. Isolated beats or sudden tempo changes become their own
    single/short sections.
    """
    tolerance = settings.marker_section_tempo_tolerance
    sections: list[list[int]] = []
    current: list[int] = [beats_ms[0]]
    for i in range(1, len(beats_ms)):
        interval = beats_ms[i] - beats_ms[i - 1]
        if len(current) >= 2:
            prev_interval = current[-1] - current[-2]
            variance = abs(interval - prev_interval) / max(1, prev_interval)
            if variance > tolerance:
                sections.append(current)
                current = [beats_ms[i]]
                continue
        current.append(beats_ms[i])
    sections.append(current)
    return sections


def apply_variety(
    base_up: float, base_down: float, variety: float, rng: random.Random,
) -> tuple[float, float]:
    """Random sub-range inside the section's tempo target. At variety=0
    returns (base_up, base_down) unchanged; higher values give the
    section a narrower, offset envelope."""
    if variety <= 0:
        return base_up, base_down
    center = (base_up + base_down) / 2
    half = (base_up - base_down) / 2
    if half < 0.5:
        return base_up, base_down
    shrink = 1.0 - variety * rng.random()
    new_half = half * shrink
    max_shift = half - new_half
    center_shift = rng.uniform(-max_shift, max_shift) if max_shift > 0 else 0.0
    return center + center_shift + new_half, center + center_shift - new_half


def emit_idle(start_ms: int, end_ms: int, idle_enabled: bool) -> list[dict]:
    """Slow oscillation between IDLE_MIN_POS and IDLE_MAX_POS to keep
    the toy moving during quiet gaps. Emits keyframes at half-period
    intervals; funscript playback interpolates between them."""
    if not idle_enabled or end_ms <= start_ms:
        return []
    period = max(500, settings.marker_idle_period_ms)
    lo = settings.marker_idle_min_pos
    hi = settings.marker_idle_max_pos
    center = (lo + hi) // 2
    half_period = max(250, period // 2)

    out: list[dict] = [{"at": start_ms, "pos": center}]
    t = start_ms + period // 4
    up = True
    while t < end_ms:
        out.append({"at": t, "pos": hi if up else lo})
        t += half_period
        up = not up
    return out


def smooth_between(
    t_start: int, t_end: int,
    pos_start: int, pos_end: int, n_points: int,
) -> list[dict]:
    """Emit n_points keyframes between two endpoints, smoothstep-eased
    so speed peaks in the middle and approaches zero at both ends.

    n=0 → no extra points (linear).
    n>=2 → symmetric smoothstep points at i/(n+1) fractions.
    """
    if n_points <= 0 or t_end <= t_start:
        return []
    dt = t_end - t_start
    dpos = pos_end - pos_start
    out: list[dict] = []
    for i in range(1, n_points + 1):
        u = i / (n_points + 1)
        eased = u * u * (3.0 - 2.0 * u)  # smoothstep
        out.append({
            "at": int(round(t_start + dt * u)),
            "pos": int(round(pos_start + dpos * eased)),
        })
    return out


def dedupe(actions: list[dict]) -> list[dict]:
    actions.sort(key=lambda a: a["at"])
    out: list[dict] = []
    for a in actions:
        a["pos"] = max(0, min(100, int(a["pos"])))
        if out and a["at"] <= out[-1]["at"]:
            a["at"] = out[-1]["at"] + 1
        out.append(a)
    return out
