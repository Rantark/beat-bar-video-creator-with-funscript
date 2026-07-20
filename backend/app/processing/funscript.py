import json
from pathlib import Path


def write_funscript(out_path: Path, actions: list[dict]) -> None:
    """Emit a valid .funscript file. actions = [{at: ms, pos: 0..100}, ...].

    We sanity-check each action here — the strictest loaders reject
    strings and out-of-range pos values silently, which is impossible
    to debug at play time.
    """
    for a in actions:
        assert isinstance(a["at"], int) and a["at"] >= 0, f"bad at: {a}"
        assert isinstance(a["pos"], int) and 0 <= a["pos"] <= 100, f"bad pos: {a}"
    payload = {"version": "1.0", "actions": actions}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload))
