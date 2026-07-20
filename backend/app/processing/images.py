"""Base64 data-URL → cv2 image utilities.

Shared by any processor that accepts an image param from the frontend
(marker template, audio bar/hit/beat sprites). Handles the parsing +
decoding once so callers just get back a BGR or BGRA array.
"""
from __future__ import annotations

import base64
import re

import cv2
import numpy as np

_DATA_URL_RE = re.compile(r"^data:image/[\w+.-]+;base64,(.+)", re.DOTALL)


def decode_data_url(payload: object, with_alpha: bool = False) -> np.ndarray | None:
    """Decode a `data:image/png;base64,...` payload from the frontend.

    Returns a BGR array by default. When `with_alpha=True`, returns BGRA
    so callers can respect a transparent-background sprite (rhythm-game
    hit markers / beat sprites need this). Returns None on any parse
    failure — treat as "no image supplied."
    """
    if not payload or not isinstance(payload, str):
        return None
    m = _DATA_URL_RE.match(payload)
    if not m:
        return None
    try:
        raw = base64.b64decode(m.group(1))
    except (ValueError, base64.binascii.Error):
        return None
    arr = np.frombuffer(raw, dtype=np.uint8)
    flag = cv2.IMREAD_UNCHANGED if with_alpha else cv2.IMREAD_COLOR
    img = cv2.imdecode(arr, flag)
    if img is None or img.size == 0:
        return None
    if with_alpha and img.ndim == 3 and img.shape[2] == 3:
        # No alpha channel — synthesize one so the caller can rely on
        # 4 channels everywhere without branching.
        alpha = np.full(img.shape[:2], 255, dtype=np.uint8)
        img = np.dstack([img, alpha])
    return img
