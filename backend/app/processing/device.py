"""Shared device selection for neural processors (audio-mode BEAT This!,
pose-mode YOLOv8-pose).

Users pick one of "auto" / "cpu" / "cuda" per job. `resolve_device`
turns that pick into a concrete torch device string that both
processors can pass to their model constructors.

"auto" checks whether the installed torch build has CUDA and whether
at least one CUDA device is visible. If it does, GPU wins; otherwise
CPU. Explicit "cuda" with no CUDA available emits a warning-return
and falls back to CPU so a job doesn't crash on a machine without a
GPU or with a CPU-only torch build.
"""
from __future__ import annotations


def resolve_device(pick: str | None) -> tuple[str, str | None]:
    """Return (device_string, note).

    device_string   : "cpu" or "cuda:0" (ready to hand to torch/ultralytics)
    note            : None on the happy path, or an English string
                      explaining any fallback (surfaced to the job log
                      so the user can see why GPU was skipped).
    """
    pref = (pick or "auto").lower()
    try:
        import torch
        cuda_available = bool(torch.cuda.is_available())
        cuda_count = int(torch.cuda.device_count()) if cuda_available else 0
    except ImportError:
        cuda_available = False
        cuda_count = 0

    if pref == "cpu":
        return "cpu", None
    if pref == "cuda":
        if cuda_available and cuda_count > 0:
            return "cuda:0", None
        return "cpu", (
            "GPU requested but CUDA is not available "
            "(install the CUDA build of PyTorch to enable GPU inference). "
            "Falling back to CPU."
        )
    # "auto"
    if cuda_available and cuda_count > 0:
        return "cuda:0", None
    return "cpu", None


def describe_device_state() -> dict:
    """Snapshot for the /api/health endpoint / UI so the user can see
    at a glance whether GPU will actually be usable."""
    try:
        import torch
        cuda_available = bool(torch.cuda.is_available())
        cuda_count = int(torch.cuda.device_count()) if cuda_available else 0
        gpu_name = (
            torch.cuda.get_device_name(0) if cuda_available and cuda_count > 0 else None
        )
        torch_build = torch.__version__
    except ImportError:
        cuda_available = False
        cuda_count = 0
        gpu_name = None
        torch_build = None
    return {
        "cuda_available": cuda_available,
        "device_count": cuda_count,
        "gpu_name": gpu_name,
        "torch_build": torch_build,
    }
