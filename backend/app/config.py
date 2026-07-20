from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        # utf-8-sig transparently strips a UTF-8 BOM if present. Windows
        # PowerShell 5.1's `Set-Content -Encoding utf8` writes one by
        # default, and without this the first line's key silently doesn't
        # match any field (extra="ignore" swallows it).
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8000

    # Explicit binary paths — safer than relying on PATH and easier to
    # change if ffmpeg moves. ffprobe is assumed to live next to ffmpeg.
    ffmpeg_path: str = r"C:\ffmpeg\bin\ffmpeg.exe"

    # Chunked upload. 2 MB is a good balance for phone hotspot uploads:
    # small enough that a dropped chunk only wastes ~2 MB of retry cost,
    # large enough that per-request overhead stays negligible.
    upload_chunk_size: int = 2 * 1024 * 1024

    # Sprite sheet layout — 1 thumb per second at 160x90, 10 cols wide.
    sprite_thumb_width: int = 160
    sprite_thumb_height: int = 90
    sprite_interval_ms: int = 1000
    sprite_cols: int = 10

    # Zone-mode smoothing + normalization tunables.
    smoothing_window: int = 11
    smoothing_polyorder: int = 3
    peak_prominence: float = 4.0
    peak_min_distance_ms: int = 80

    # Rolling auto-range for zone mode. Global min→0, max→100 flattens
    # amplitude variation across sections; a rolling window keeps a calm
    # passage and an intense passage each mapped to their own local
    # range. Set the window wide enough to span several full strokes so
    # it doesn't chase individual peaks. min_amplitude_px acts as a
    # floor on the local range so that a still section doesn't amplify
    # LK noise into fake full-swing strokes.
    zone_rolling_window_ms: int = 3000
    zone_min_amplitude_px: float = 5.0

    # Marker-mode (point-color) beat detection.
    #   MARKER_PROMINENCE       Min color-deviation prominence, 0-100 scale
    #                           (L2 BGR distance / 4.417). Higher = only
    #                           dramatic color changes count as beats.
    #   MARKER_MIN_DISTANCE_MS  Min ms between beats (5 Hz cap by default).
    #   MARKER_BASELINE_WINDOW_MS Rolling median window for the "normal"
    #                           color at the hit point. Wide enough to
    #                           dominate over single-frame beat flashes.
    marker_prominence: float = 15.0
    # Lowered from 200 so tightly-spaced beats aren't merged. At 100ms
    # we still cap at 10 beats/sec, which is faster than any realistic
    # rhythm content but permissive enough to catch dense sequences.
    marker_min_distance_ms: int = 100
    marker_baseline_window_ms: int = 2000

    # Smoothstep interpolation points inserted between each beat and its
    # next peak (and between peak and next beat). Level 0 = raw triangle
    # wave (abrupt direction change at every reversal). Level 2-3 shape
    # each half-cycle into an S-curve so the toy accelerates/decelerates
    # gradually around the extremes.
    marker_motion_smoothing: int = 2

    # Marker-mode stroke shaping — interval thresholds. Strokes whose
    # beat-to-beat interval is <= fast use max_down_fast (shallow);
    # >= slow use max_down (deep); between, downstroke depth interpolates
    # linearly. Peak (max_up) is the same for every stroke.
    marker_fast_interval_ms: int = 250
    marker_slow_interval_ms: int = 1000

    # Combined beat signal has two components:
    #   contrast — spatial: |inner_circle_mean - outer_annulus_mean|.
    #     Cancels animated backgrounds because both regions see the
    #     same background changes; only lights up when a marker
    #     specifically overlays the inner circle.
    #   delta — temporal: frame-to-frame change in the inner mean.
    #     Fallback for solid-background content where a same-colored
    #     marker doesn't produce spatial contrast.
    # signal = contrast_weight * contrast + delta_weight * delta.
    marker_contrast_weight: float = 1.0
    marker_delta_weight: float = 0.5
    # HSV signal components — often more discriminative than BGR on
    # translucent, saturated markers over animated content. Hue distance
    # ignores brightness; saturation catches "colored overlay on greyish
    # video" cases where BGR contrast is subtle.
    marker_hue_weight: float = 0.5
    marker_sat_weight: float = 0.5
    # Template matching (optional per-job). Weight of the match-score
    # signal when a template image is uploaded with the job.
    marker_template_weight: float = 1.5
    # Outer annulus geometry, as multiples of the user's marker radius.
    marker_outer_start_factor: float = 1.5
    marker_outer_end_factor: float = 2.5

    # Section-based amplitude — groups of similar-tempo consecutive
    # beats (interval variance under this fraction) share one amplitude
    # so rhythmic passages get consistent stroke heights.
    marker_section_tempo_tolerance: float = 0.2

    # Cross-section variety (0..1). 0 = every section uses its exact
    # tempo target; 1 = sections randomize within that target's envelope.
    # Randomness is seeded from the beat pattern so re-runs are stable.
    marker_variety_amount: float = 0.0

    # Idle animation for silent gaps (start of video, between sections,
    # after last beat). Skipped for gaps shorter than the threshold —
    # brief pauses interpolate naturally between neighbouring keyframes.
    marker_idle_enabled: bool = True
    marker_idle_gap_threshold_ms: int = 2000
    marker_idle_period_ms: int = 3000
    marker_idle_min_pos: int = 30
    marker_idle_max_pos: int = 70

    @property
    def storage_dir(self) -> Path:
        return BACKEND_ROOT / "storage"

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def uploads_tmp_dir(self) -> Path:
        return self.uploads_dir / ".tmp"

    @property
    def sprites_dir(self) -> Path:
        return self.storage_dir / "sprites"

    @property
    def output_dir(self) -> Path:
        return self.storage_dir / "output"

    @property
    def db_path(self) -> Path:
        return self.storage_dir / "app.db"

    @property
    def ffprobe_path(self) -> str:
        return str(Path(self.ffmpeg_path).with_name("ffprobe.exe"))


settings = Settings()
