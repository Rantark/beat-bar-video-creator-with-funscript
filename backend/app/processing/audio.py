"""Audio-driven beat processor.

Produces a funscript purely from the source video's audio track — no
visible beat bar required. Useful for content where the rhythm is
carried by the music but the video itself has no on-screen marker to
track.

Pipeline
--------
1. ffmpeg-extract mono PCM
2. spectral-flux onset detection (`audio_beats.detect_onsets`)
3. `beat_actions.beats_to_actions()` (same shape/section pipeline as
   marker/line modes)
4. optional debug MP4 with a synthetic beat bar rendered along the
   bottom of the frame + red flash on each detected onset
"""
import json
from pathlib import Path
from typing import Callable

from app.config import settings
from app.processing import audio_beats, beat_actions
from app.processing.base import VideoInfo
from app.processing.funscript import write_funscript
from app.processing.images import decode_data_url


class AudioProcessor:
    def run(
        self,
        video: VideoInfo,
        params: dict,
        out_path: Path,
        progress_cb: Callable[[float], None],
        debug_out_path: Path | None = None,
    ) -> None:
        audio = params.get("audio") or {}

        max_up = float(audio.get("max_up", 100))
        max_down = float(audio.get("max_down", 0))
        max_up_fast = float(audio.get("max_up_fast", max_up))
        max_down_fast = float(audio.get("max_down_fast", max_down))
        max_up = max(0.0, min(100.0, max_up))
        max_down = max(0.0, min(100.0, max_down))
        if max_down > max_up:
            max_down, max_up = max_up, max_down
        max_up_fast = max(max_down, min(max_up, max_up_fast))
        max_down_fast = max(max_down, min(max_up_fast, max_down_fast))

        variety_amount = max(
            0.0, min(1.0, float(audio.get("variety_amount", settings.marker_variety_amount))),
        )
        idle_enabled = bool(audio.get("idle_enabled", settings.marker_idle_enabled))
        motion_smoothing = max(
            0, min(4, int(audio.get("motion_smoothing", settings.marker_motion_smoothing))),
        )

        sensitivity = max(0.0, min(1.0, float(audio.get("sensitivity", 0.5))))
        low_hz = float(audio.get("low_hz", 60))
        high_hz = float(audio.get("high_hz", 8000))
        min_gap_ms = max(20, int(audio.get("min_gap_ms", 120)))
        regularize = bool(audio.get("regularize", True))
        section_min_ms = max(5000, int(audio.get("section_min_ms", 10000)))
        section_target_ms = max(section_min_ms, int(audio.get("section_target_ms", 20000)))
        section_max_ms = max(section_target_ms, int(audio.get("section_max_ms", 30000)))
        section_fluctuation = max(0.0, min(1.0, float(audio.get("section_fluctuation", 0.0))))
        pattern_variety = max(0.0, min(1.0, float(audio.get("pattern_variety", 0.0))))

        # User-defined beat patterns. Each pattern is a fixed-length
        # array of booleans representing beat slots at the section's
        # detected period. Coerce liberally — the frontend sends
        # arrays of booleans but nothing here should crash on stray
        # values from a saved-preset that predates the field.
        raw_patterns = audio.get("patterns") or []
        patterns: list[list[bool]] = []
        if isinstance(raw_patterns, list):
            for p in raw_patterns:
                if isinstance(p, list) and len(p) >= 2:
                    patterns.append([bool(x) for x in p])

        progress_cb(0.05)
        pcm = audio_beats.extract_audio_pcm(video.path, sample_rate=22050)
        progress_cb(0.35)

        if pcm.size == 0:
            # No audio track. Emit a hold at the midpoint so downstream
            # editor still has something to work with, mark done.
            write_funscript(out_path, [{"at": 0, "pos": int(round((max_up + max_down) / 2))}])
            progress_cb(1.0)
            return

        onset_ms, novelty, hop_ms = audio_beats.detect_onsets(
            pcm, 22050,
            sensitivity=sensitivity,
            min_gap_ms=min_gap_ms,
            low_hz=low_hz,
            high_hz=high_hz,
        )
        progress_cb(0.7)

        # Clamp onset times to video duration — audio streams occasionally
        # run a few ms longer than the video track.
        onset_ms = [t for t in onset_ms if 0 <= t <= video.duration_ms]

        # Regularize: lock a steady tempo per ~20s section so the toy
        # doesn't chase every incidental sound. Sections with too few
        # onsets pass through raw; silent sections drop out entirely so
        # the idle animation takes over there.
        section_meta: list[dict] = []
        if regularize:
            onset_ms, section_meta = audio_beats.regularize_beats(
                onset_ms, novelty, hop_ms, video.duration_ms,
                section_min_ms=section_min_ms,
                section_target_ms=section_target_ms,
                section_max_ms=section_max_ms,
                section_fluctuation=section_fluctuation,
                pattern_variety=pattern_variety,
                patterns=patterns,
            )

        actions = beat_actions.beats_to_actions(
            onset_ms, video.duration_ms,
            max_up=max_up, max_down=max_down,
            max_up_fast=max_up_fast, max_down_fast=max_down_fast,
            variety_amount=variety_amount,
            idle_enabled=idle_enabled,
            motion_smoothing=motion_smoothing,
        )
        write_funscript(out_path, actions)

        # Persist section + pattern metadata next to the funscript so
        # the editor can draw section boundaries, jump to a section by
        # button, and re-apply a pattern to a specific section.
        meta_path = out_path.with_suffix(".meta.json")
        meta_path.write_text(json.dumps({
            "sections": section_meta,
            "patterns": patterns,
        }), encoding="utf-8")

        progress_cb(0.85)

        if debug_out_path is not None:
            from app.processing.debug import render_audio_debug
            fps = video.fps if video.fps > 0 else 30.0
            beat_frames = [int(round(t / 1000.0 * fps)) for t in onset_ms]
            # Optional custom sprites — bar background is opaque BGR;
            # hit and beat sprites keep alpha so a transparent PNG
            # composites cleanly onto the underlying video.
            bar_img = decode_data_url(audio.get("bar_image"), with_alpha=False)
            hit_img = decode_data_url(audio.get("hit_image"), with_alpha=True)
            beat_img = decode_data_url(audio.get("beat_image"), with_alpha=True)
            lookahead_ms = max(200, int(audio.get("lookahead_ms", 1500)))

            def render_progress(p: float) -> None:
                progress_cb(0.85 + p * 0.15)

            render_audio_debug(
                source_video=video.path,
                out_path=debug_out_path,
                beat_frame_indices=beat_frames,
                beat_times_ms=onset_ms,
                video_duration_ms=video.duration_ms,
                novelty=novelty,
                novelty_hop_ms=hop_ms,
                bar_image=bar_img,
                hit_image=hit_img,
                beat_image=beat_img,
                lookahead_ms=lookahead_ms,
                progress_cb=render_progress,
            )
        progress_cb(1.0)
