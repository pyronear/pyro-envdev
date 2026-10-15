#!/usr/bin/env python3
"""Live controller for interactive day replays (replay_day.py --ctl).

Drives the simulated clock that both the API and the replay driver follow, by
appending segments to replay_control/clock.json. Everything reacts instantly —
no restarts.

Commands:
  status            current simulated time, speed, and the next steps
  pause             freeze the simulation
  play [SPEED]      resume at SPEED x (default 60)
  slow [SPEED]      shorthand for a watchable pace (default 10)
  next [SPEED]      fast-forward to 3 simulated minutes after the next
                    sequence start (its images are already visible), then
                    PAUSE (default). Pass SPEED to resume instead, e.g.
                    `next 10`.
  goto HH:MM [SPEED]  fast-forward to a simulated time of day, then PAUSE
                    (default). Pass SPEED to resume playing instead, e.g.
                    `goto 12h00 10`. HH:MM is PARIS time (what the platform
                    displays); accepts 12:00, 12h00 or 12h.

Examples:
  python3 scripts/replay_ctl.py status
  python3 scripts/replay_ctl.py next        # saute au prochain épisode, 10x
  python3 scripts/replay_ctl.py play 60     # reprend la journée à 60x
"""

import json
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from replay_clock import STEPS_FILE, append_segment, read_segments, real_utcnow, sim_now

# Bounded so the per-camera posting queue never lags the clock: at higher speeds
# the timestamps of in-flight frames bunch up at the end of the seek and the
# bbox chain can break, splitting a sequence in two. 60x is the fastest pace
# validated against prod (full-day run, zero splits).
SEEK_SPEED = 60.0
PARIS = ZoneInfo("Europe/Paris")


def paris(dt):
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(PARIS).strftime("%Hh%Mm%Ss")


def load_steps():
    try:
        return [
            {"sim_t": datetime.fromisoformat(s["sim_t"]), "label": s["label"]}
            for s in json.loads(STEPS_FILE.read_text())
        ]
    except (OSError, json.JSONDecodeError):
        return []


def cmd_status():
    sim, speed = sim_now()
    state = "⏸ pause" if speed == 0 else f"▶ {speed:g}x"
    print(f"heure simulée: {paris(sim)} (Paris) | {state}")
    upcoming = [s for s in load_steps() if s["sim_t"] > sim][:5]
    if upcoming:
        print("prochaines étapes:")
        for s in upcoming:
            print(f"  {paris(s['sim_t'])}  {s['label']}")
    else:
        print("plus d'étape à venir")


def seek_to(target, cruise):
    sim, _ = sim_now()
    if target <= sim:
        print(f"déjà passé ({paris(target)} <= {paris(sim)})")
        return
    now = real_utcnow()
    seek_real_duration = (target - sim) / SEEK_SPEED
    append_segment(sim, SEEK_SPEED, real0=now)
    append_segment(target, cruise, real0=now + seek_real_duration)
    then = "pause" if cruise == 0 else f"{cruise:g}x"
    print(
        f"⏩ avance rapide {paris(sim)} -> {paris(target)}"
        f" ({seek_real_duration.total_seconds():.0f} s réelles), puis {then}"
    )


def main():
    args = sys.argv[1:]
    # tolerate `goto status`, `goto pause`...: the command word wins
    if len(args) >= 2 and args[0] == "goto" and args[1] in ("status", "pause", "play", "slow", "next"):
        args = args[1:]
    cmd = args[0] if args else "status"
    if cmd == "status":
        cmd_status()
    elif cmd == "pause":
        sim, _ = sim_now()
        append_segment(sim, 0)
        print(f"⏸ pause à {paris(sim)}")
    elif cmd in ("play", "slow"):
        default = 60.0 if cmd == "play" else 10.0
        speed = float(args[1]) if len(args) > 1 else default
        sim, _ = sim_now()
        append_segment(sim, speed)
        print(f"▶ {speed:g}x depuis {paris(sim)}")
    elif cmd == "next":
        cruise = float(args[1]) if len(args) > 1 else 0.0
        sim, _ = sim_now()
        upcoming = [s for s in load_steps() if s["sim_t"] > sim]
        if not upcoming:
            print("plus d'étape à venir")
            return
        step = upcoming[0]
        print(f"étape suivante: {step['label']}")
        # land 3 simulated minutes AFTER the sequence start, so its first images
        # are already ingested and visible on the platform
        seek_to(step["sim_t"] + timedelta(minutes=3), cruise)
    elif cmd == "goto":
        if len(args) < 2:
            sys.exit("usage: goto HH:MM [SPEED] (heure de Paris, ex: goto 12h00)")
        m_ = __import__("re").match(r"^(\d{1,2})[:hH](\d{0,2})$", args[1])
        if not m_:
            sys.exit(
                f"heure invalide: {args[1]} (attendu HH:MM ou HHhMM)\n"
                "rappel: status/pause/play/slow/next sont des commandes directes,"
                " ex: python3 scripts/replay_ctl.py status"
            )
        h, m = int(m_.group(1)), int(m_.group(2) or 0)
        cruise = float(args[2]) if len(args) > 2 else 0.0
        sim, _ = sim_now()
        # HH:MM is Paris local; the simulated clock is naive UTC
        paris_now = sim.replace(tzinfo=ZoneInfo("UTC")).astimezone(PARIS)
        target_paris = paris_now.replace(hour=h, minute=m, second=0, microsecond=0)
        target = target_paris.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        seek_to(target, cruise)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
