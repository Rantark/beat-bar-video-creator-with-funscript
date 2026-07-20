from pathlib import Path
from typing import Callable

from app.processing.base import VideoInfo
from app.processing.funscript import write_funscript


class StubProcessor:
    """Emits a metronomic stroke pattern for the video's full duration.

    Lets us verify the upload -> job -> download loop end-to-end without
    trusting the CV code. Real zone / line processors replace this in
    phase 3 while keeping the same interface.
    """

    def run(
        self,
        video: VideoInfo,
        params: dict,
        out_path: Path,
        progress_cb: Callable[[float], None],
    ) -> None:
        # ~1.25 strokes/sec, one action per peak/trough — same shape a
        # real script has, so the download loop is exercised realistically.
        period_ms = 800
        half = period_ms // 2
        actions: list[dict] = []
        t = 0
        last_progress_ms = 0
        while t < video.duration_ms:
            actions.append({"at": t, "pos": 0})
            actions.append({"at": t + half, "pos": 100})
            t += period_ms
            # Throttle progress writes to ~4 Hz on the video timeline.
            if t - last_progress_ms >= 4000:
                progress_cb(min(0.99, t / video.duration_ms))
                last_progress_ms = t
        progress_cb(1.0)
        write_funscript(out_path, actions)
