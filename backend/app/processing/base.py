from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


@dataclass
class VideoInfo:
    id: str
    path: Path
    duration_ms: int
    width: int
    height: int
    fps: float


class Processor(Protocol):
    """A Processor turns (video + params) into a funscript file.

    progress_cb receives a value in [0, 1] and is safe to call frequently;
    implementations should throttle to avoid hammering SQLite.

    debug_out_path (when supplied) is where the processor should write
    an annotated MP4 showing what it "saw" — overlays plus a red flash
    on each event frame. Enables the user to verify sync visually in
    any player. Rendering it is expensive; only pass when requested.
    """

    def run(
        self,
        video: VideoInfo,
        params: dict,
        out_path: Path,
        progress_cb: Callable[[float], None],
        debug_out_path: Path | None = None,
    ) -> None:
        ...
