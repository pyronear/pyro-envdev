"""Shared helpers for the file-driven replay clock (clock.json segments)."""

import json
from datetime import datetime, timezone
from pathlib import Path

ENVDEV_ROOT = Path(__file__).resolve().parent.parent
CONTROL_DIR = ENVDEV_ROOT / "replay_control"
CLOCK_FILE = CONTROL_DIR / "clock.json"
STEPS_FILE = CONTROL_DIR / "steps.json"


def real_utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def read_segments():
    try:
        data = json.loads(CLOCK_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    segs = [
        (datetime.fromisoformat(s["real0"]), datetime.fromisoformat(s["sim0"]), float(s["speed"]))
        for s in data.get("segments", [])
    ]
    return sorted(segs, key=lambda s: s[0])


def write_segments(segments):
    CONTROL_DIR.mkdir(exist_ok=True)
    payload = {
        "segments": [
            {"real0": r.isoformat(), "sim0": s.isoformat(), "speed": sp} for r, s, sp in segments
        ]
    }
    tmp = CLOCK_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1))
    tmp.replace(CLOCK_FILE)


def sim_now(segments=None, now=None):
    segments = read_segments() if segments is None else segments
    now = now or real_utcnow()
    if not segments:
        return now, 1.0
    active = None
    for seg in segments:
        if seg[0] <= now:
            active = seg
        else:
            break
    if active is None:
        return segments[0][1], 0.0
    real0, sim0, speed = active
    return sim0 + (now - real0) * speed, speed


def append_segment(sim0, speed, real0=None):
    """Anchor a new segment at `real0` (default: now) starting from sim time `sim0`."""
    segments = read_segments()
    real0 = real0 or real_utcnow()
    segments = [s for s in segments if s[0] < real0]
    segments.append((real0, sim0, float(speed)))
    write_segments(segments)
