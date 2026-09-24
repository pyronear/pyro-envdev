#!/usr/bin/env python3
"""Replay a real production day against the local pyro-envdev API, time-accelerated.

Reads the day dump produced by the analyse77 download pipeline
(<data>/<day>/alert_*/sequence_*/{sequence.json,detections.json,images/*.jpg}),
maps prod cameras/poses onto the local dev environment (creating missing poses
with the prod azimuths), then re-posts every detection (image + bboxes) in
chronological order, with all inter-detection gaps divided by --speed.

Two modes:

--clock (recommended): the API image must carry the simulated-clock patch
  (pyro-api branch replay-clock-20260710). The script restarts pyro_api with an
  accelerated clock anchored on TODAY at the day's real hours: detections land in
  the DB with the historical times-of-day, the platform's live view shows the day
  unfolding, and every utcnow-anchored window behaves exactly as in production
  (no window scaling needed).

legacy mode (no --clock): posts at "now" and optionally rewrites timestamps to
  the historical date at the end (see --no-restore-times / live_retimer.py);
  requires the scaled-window overrides.

Usage:
  python3 scripts/replay_day.py --day 2026-07-10 --speed 60 --clock
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_clock import CLOCK_FILE, STEPS_FILE, append_segment, sim_now, write_segments  # noqa: E402

ENVDEV_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DATA = Path.home() / "pyronear/test/analyse77"
DEFAULT_API = "http://localhost:5050"


def api_login(api, login, pwd):
    r = requests.post(f"{api}/api/v1/login/creds", data={"username": login, "password": pwd}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def parse_bboxes(s):
    if not s:
        return []
    try:
        v = ast.literal_eval(s)
        boxes = [tuple(b) for b in v] if isinstance(v, (list, tuple)) else []
    except (ValueError, SyntaxError):
        return []
    # drop degenerate boxes (e.g. the (0,0,0,0,0) prod placeholder): the API 422s on xmin>=xmax
    return [b for b in boxes if round(b[0], 3) < round(b[2], 3) and round(b[1], 3) < round(b[3], 3)]


def _fmt_float(x):
    # API FLOAT_PATTERN accepts `0`, `1` or `0.xxx` (max 3 decimals) — never `1.0`/`0.0`
    s = f"{round(float(x), 3):.3f}".rstrip("0").rstrip(".")
    return s or "0"


def fmt_bboxes(boxes):
    return "[" + ",".join("(" + ",".join(_fmt_float(x) for x in b) + ")" for b in boxes) + "]"


def load_day(data_dir, day):
    """Collect unique sequences and their detections + image paths."""
    day_dir = data_dir / day
    if not day_dir.is_dir():
        sys.exit(f"day folder not found: {day_dir}")
    sequences = {}  # prod_seq_id -> {"meta":..., "dets":[...]}
    for sdir in sorted(day_dir.glob("alert_*/sequence_*")):
        meta = json.load(open(sdir / "sequence.json"))
        if meta["id"] in sequences:
            continue  # sequence shared by several alerts: keep first folder
        dets = json.load(open(sdir / "detections.json"))
        img_by_det = {}
        for img in (sdir / "images").glob("*.jpg"):
            m = re.search(r"det(\d+)", img.name)
            if m:
                img_by_det[int(m.group(1))] = img
        sequences[meta["id"]] = {"meta": meta, "dets": dets, "imgs": img_by_det}
    return sequences


def _recreate_api(env):
    subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.replay.yml",
         "up", "-d", "--force-recreate", "pyro_api"],
        cwd=ENVDEV_ROOT, env=env, check=True, capture_output=True, text=True,
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            if requests.get(f"{DEFAULT_API}/status", timeout=3).ok:
                print("   API prête")
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    sys.exit("l'API n'est pas revenue après le redémarrage")


def restart_api_with_clock(speed, sim0, real0):
    """Recreate pyro_api with the fixed simulated-clock env, then wait for health."""
    CLOCK_FILE.unlink(missing_ok=True)  # the clock file would take priority over the env
    env = {
        **os.environ,
        "REPLAY_CLOCK_SPEED": f"{speed:g}",
        "REPLAY_CLOCK_SIM_ORIGIN": sim0.isoformat(),
        "REPLAY_CLOCK_REAL_ORIGIN": real0.isoformat(),
    }
    print(f"🕰  redémarrage de l'API avec l'horloge simulée: {sim0.isoformat()} @ {speed:g}x")
    _recreate_api(env)


def restart_api_plain():
    """Recreate pyro_api without fixed-clock env: it follows replay_control/clock.json."""
    print("🕰  redémarrage de l'API sur l'horloge pilotable (replay_control/clock.json)")
    _recreate_api({**os.environ})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--day", required=True, help="e.g. 2026-07-10")
    ap.add_argument("--speed", type=float, default=60.0, help="time compression factor (default 60)")
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--login", default="mateo", help="local superadmin login (.env)")
    ap.add_argument("--pwd", default="mateo", help="local superadmin password (.env)")
    ap.add_argument("--view-login", default="test77", help="org agent used for the final summary")
    ap.add_argument("--view-pwd", default="test")
    ap.add_argument("--clock", action="store_true",
                    help="simulated-clock mode: today's date + the day's real hours (recommended)")
    ap.add_argument("--ctl", action="store_true",
                    help="interactive mode: file-driven clock, starts PAUSED; drive it with"
                         " scripts/replay_ctl.py (pause/play/slow/next/goto)")
    ap.add_argument("--dry-run", action="store_true", help="map + schedule only, no POSTs")
    ap.add_argument(
        "--no-restore-times", action="store_true",
        help="legacy mode only: skip rewriting DB timestamps to the prod times after the replay",
    )
    ap.add_argument(
        "--map-file", type=Path, default=ENVDEV_ROOT / ".replay_map.jsonl",
        help="legacy mode only: mapping file consumed by scripts/live_retimer.py",
    )
    args = ap.parse_args()

    sequences = load_day(args.data, args.day)
    first_t = min(
        datetime.fromisoformat(det["created_at"]) for s in sequences.values() for det in s["dets"]
    )

    real0 = sim0 = None
    if args.ctl:
        args.clock = True
        # today's date, the day's real hours; simulation starts PAUSED just before the
        # first detection — advance it with scripts/replay_ctl.py
        sim0 = datetime.combine(date.today(), first_t.time()) - timedelta(seconds=30)
        if not args.dry_run:
            write_segments([(datetime.now(timezone.utc).replace(tzinfo=None), sim0, 0.0)])
            print(f"🕹  mode interactif: horloge en PAUSE à {sim0.isoformat()} — pilotez avec"
                  f" scripts/replay_ctl.py (status/pause/play/slow/next/goto)")
            restart_api_plain()
    elif args.clock:
        # today's date, the day's real hours
        sim0 = datetime.combine(date.today(), first_t.time()) - timedelta(seconds=30)
        real0 = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=45)
        if not args.dry_run:
            restart_api_with_clock(args.speed, sim0, real0)
    else:
        print(f"⚙️  For --speed {args.speed:g}, the API must run with scaled windows, e.g.:")
        for var, default in (
            ("SEQUENCE_MIN_INTERVAL_SECONDS", 300),
            ("SEQUENCE_RELAXATION_SECONDS", 7200),
            ("TRIANGULATION_RELAXATION_SECONDS", 1800),
        ):
            print(f"    {var}={max(1, round(default / args.speed))}")
        print("    (see docker-compose.replay.yml)\n")

    admin = api_login(args.api, args.login, args.pwd)

    # Map prod camera names -> local ids
    r = requests.get(f"{args.api}/api/v1/cameras/", headers=auth(admin), timeout=30)
    r.raise_for_status()
    local_cams = {c["name"]: c["id"] for c in r.json()}

    prod_cams = {}  # prod camera id -> name (from analyse77 cameras.json)
    cam_file = args.data / args.day / "cameras.json"
    if not cam_file.exists():
        cam_file = args.data / "cameras.json"
    for c in json.load(open(cam_file)):
        prod_cams[c["id"]] = c["name"]

    # Camera tokens
    cam_tokens = {}
    for name, cid in local_cams.items():
        if name not in {prod_cams[s["meta"]["camera_id"]] for s in sequences.values()}:
            continue
        r = requests.post(f"{args.api}/api/v1/cameras/{cid}/token", headers=auth(admin), timeout=30)
        r.raise_for_status()
        cam_tokens[name] = r.json()["access_token"]

    # Ensure poses: prod (camera, pose_id) -> local pose id with same azimuth
    pose_map = {}  # (cam_name, prod_pose_id) -> local_pose_id
    local_poses = {}  # cam_name -> {azimuth: id}
    for name, token in cam_tokens.items():
        r = requests.get(f"{args.api}/api/v1/poses/", headers=auth(token), timeout=30)
        r.raise_for_status()
        local_poses[name] = {round(float(p["azimuth"]), 1): p["id"] for p in r.json()}
    for seq in sequences.values():
        m = seq["meta"]
        name = prod_cams[m["camera_id"]]
        key = (name, m["pose_id"])
        if key in pose_map:
            continue
        az = round(float(m["camera_azimuth"]), 1)
        if az in local_poses[name]:
            pose_map[key] = local_poses[name][az]
            continue
        payload = {"camera_id": local_cams[name], "azimuth": az, "patrol_id": m["pose_id"]}
        r = requests.post(f"{args.api}/api/v1/poses/", headers=auth(admin), json=payload, timeout=30)
        r.raise_for_status()
        pose_map[key] = r.json()["id"]
        local_poses[name][az] = pose_map[key]
        print(f"pose créée: {name} az={az}° (prod pose {m['pose_id']}) -> local pose {pose_map[key]}")

    # Build the chronological event list
    events = []
    for seq in sequences.values():
        m = seq["meta"]
        name = prod_cams[m["camera_id"]]
        for det in seq["dets"]:
            img = seq["imgs"].get(det["id"])
            if img is None:
                continue
            boxes = parse_bboxes(det.get("bbox")) + parse_bboxes(det.get("others_bboxes"))
            if not boxes:
                continue
            t = datetime.fromisoformat(det["created_at"])
            events.append({
                "t": t,
                "sim_t": datetime.combine(date.today(), t.time()) if args.clock else t,
                "cam": name,
                "pose": pose_map[(name, m["pose_id"])],
                "bboxes": fmt_bboxes(boxes),
                "img": img,
                "seq": m["id"],
            })
    events.sort(key=lambda e: e["t"])
    if not events:
        sys.exit("no detections to replay")
    if args.ctl and not args.dry_run:
        # one step per sequence start, for replay_ctl.py `next`
        seq_count = {}
        for ev in events:
            seq_count[ev["seq"]] = seq_count.get(ev["seq"], 0) + 1
        steps, seen = [], set()
        for ev in events:
            if ev["seq"] in seen:
                continue
            seen.add(ev["seq"])
            steps.append({
                "sim_t": ev["sim_t"].isoformat(),
                "label": f"seq {ev['seq']} {ev['cam']} ({seq_count[ev['seq']]} dets)",
            })
        STEPS_FILE.write_text(json.dumps(steps, indent=1))
    t0, tn = events[0]["t"], events[-1]["t"]
    real = (tn - t0).total_seconds()
    print(f"\n▶️  {len(events)} détections de {len(sequences)} séquences")
    print(f"   journée réelle {t0:%H:%M:%S}->{tn:%H:%M:%S} UTC ({real / 3600:.1f} h)"
          f" -> replay ~{real / args.speed / 60:.1f} min à {args.speed:g}x")
    if args.clock:
        print(f"   heures simulées sur AUJOURD'HUI ({date.today().isoformat()}) — la vue live"
              " de la plateforme suit la journée\n")
    if args.dry_run:
        return

    stats = {"ok": 0, "err": 0}
    id_times = []  # (local_detection_id, prod_created_at_iso) — legacy retiming
    id_lock = threading.Lock()
    seq_totals = {}
    for ev in events:
        seq_totals[ev["seq"]] = seq_totals.get(ev["seq"], 0) + 1
    map_fh = None if args.clock else open(args.map_file, "w")  # legacy: live_retimer.py

    def post(ev):
        try:
            with open(ev["img"], "rb") as f:
                r = requests.post(
                    f"{args.api}/api/v1/detections/",
                    headers=auth(cam_tokens[ev["cam"]]),
                    data={"bboxes": ev["bboxes"], "pose_id": ev["pose"]},
                    files={"file": (ev["img"].name, f, "image/jpeg")},
                    timeout=60,
                )
            if r.status_code == 201:
                stats["ok"] += 1
                with id_lock:
                    id_times.append((r.json()["id"], ev["t"].isoformat()))
                    if map_fh is not None:
                        map_fh.write(json.dumps({
                            "id": r.json()["id"], "ts": ev["t"].isoformat(), "seq": ev["seq"],
                            "posted": time.time(), "total": seq_totals[ev["seq"]],
                        }) + "\n")
                        map_fh.flush()
            else:
                stats["err"] += 1
                print(f"  ✗ seq {ev['seq']} {ev['img'].name}: {r.status_code} {r.text[:120]}")
        except Exception as e:  # noqa: BLE001
            stats["err"] += 1
            print(f"  ✗ seq {ev['seq']} {ev['img'].name}: {e}")

    # One single-worker executor per camera: a real camera posts sequentially, and
    # concurrent same-camera posts race the API's sequence creation (duplicate and
    # orphan sequences). Cross-camera concurrency stays.
    cam_pools = {name: ThreadPoolExecutor(max_workers=1) for name in cam_tokens}

    if args.ctl:
        # sim-time-driven loop: follows the controllable clock (pause/seek aware)
        i = 0
        last_report = 0.0
        while i < len(events):
            sim, speed = sim_now()
            while i < len(events) and events[i]["sim_t"] <= sim:
                cam_pools[events[i]["cam"]].submit(post, events[i])
                i += 1
            if time.time() - last_report > 30:
                state = "pause" if speed == 0 else f"{speed:g}x"
                print(f"  {i}/{len(events)} envoyées | heure simulée {sim:%H:%M:%S} UTC ({state})"
                      f" | ok={stats['ok']} err={stats['err']}")
                last_report = time.time()
            time.sleep(0.25)
        for pool in cam_pools.values():
            pool.shutdown(wait=True)
    else:
        if args.clock:
            real0_epoch = real0.replace(tzinfo=timezone.utc).timestamp()

            def target_epoch(ev):
                return real0_epoch + (ev["sim_t"] - sim0).total_seconds() / args.speed
        else:
            start = time.time()

            def target_epoch(ev):
                return start + (ev["t"] - t0).total_seconds() / args.speed

        for i, ev in enumerate(events):
            delay = target_epoch(ev) - time.time()
            if delay > 0:
                time.sleep(delay)
            cam_pools[ev["cam"]].submit(post, ev)
            if (i + 1) % 200 == 0:
                print(f"  {i + 1}/{len(events)} envoyées (heure simulée {ev['t']:%H:%M} UTC,"
                      f" ok={stats['ok']} err={stats['err']})")
        for pool in cam_pools.values():
            pool.shutdown(wait=True)

    if args.ctl:
        # settle the clock at real-time pace so the day stays visible in the live view
        sim, _ = sim_now()
        append_segment(sim, 1.0)
        print(f"🕰  fin des événements: horloge stabilisée à 1x ({sim:%H:%M:%S} UTC simulé)")

    print(f"\n⏳ envoi terminé ({stats['ok']} ok, {stats['err']} erreurs), attente validation (15 s)...")
    time.sleep(15)
    if map_fh is not None:
        with id_lock:
            map_fh.write(json.dumps({"done": True}) + "\n")
            map_fh.close()

    result_date = date.today().isoformat()
    if not args.clock and not args.no_restore_times and id_times:
        print(f"🕐 réécriture des vraies heures prod dans la base locale ({len(id_times)} détections)...")
        values = ",".join(f"({i},'{ts}')" for i, ts in id_times)
        sql = f"""
BEGIN;
UPDATE detections d SET created_at = v.ts::timestamp
FROM (VALUES {values}) AS v(id, ts) WHERE d.id = v.id;
UPDATE sequences s SET started_at = sub.mn, last_seen_at = sub.mx
FROM (SELECT sequence_id, MIN(created_at) mn, MAX(created_at) mx
      FROM detections WHERE sequence_id IS NOT NULL GROUP BY sequence_id) sub
WHERE s.id = sub.sequence_id;
UPDATE alerts a SET started_at = sub.mn, last_seen_at = sub.mx
FROM (SELECT asq.alert_id, MIN(s.started_at) mn, MAX(s.last_seen_at) mx
      FROM alerts_sequences asq JOIN sequences s ON s.id = asq.sequence_id
      GROUP BY asq.alert_id) sub
WHERE a.id = sub.alert_id;
COMMIT;
"""
        proc = subprocess.run(
            ["docker", "compose", "exec", "-T", "db", "psql",
             "-U", "dummy_pg_user", "-d", "dummy_pg_db", "-v", "ON_ERROR_STOP=1", "-f", "-"],
            input=sql, text=True, cwd=ENVDEV_ROOT, capture_output=True,
        )
        if proc.returncode != 0:
            print(f"  ✗ retiming KO: {proc.stderr.strip()[:400]}")
        else:
            result_date = args.day
            print(f"  ✓ horodatages restaurés — la plateforme affiche la journée du {args.day}")

    # pre-#633 the admin cannot list other orgs' alerts: use the org agent account
    viewer = api_login(args.api, args.view_login, args.view_pwd)
    r = requests.get(
        f"{args.api}/api/v1/alerts/all/fromdate", params={"from_date": result_date, "limit": 100},
        headers=auth(viewer), timeout=30,
    )
    alerts = r.json() if r.ok else []
    print(f"\n📊 RÉSULTAT: {len(alerts)} alertes créées par le replay")
    for a in sorted(alerts, key=lambda a: a["started_at"]):
        seqs = a.get("sequences") or []
        loc = f"({a['lat']:.5f},{a['lon']:.5f})" if a.get("lat") is not None else "sans loc"
        cams = sorted({s.get("camera_id") for s in seqs})
        print(f"  alerte {a['id']}: {a['started_at'][11:19]}Z->{a['last_seen_at'][11:19]}Z | {loc}"
              f" | {len(seqs)} seq | cams locales {cams}")
    print("\n👀 Frontend: http://localhost:8080/  ·  API: http://localhost:5050/docs")


if __name__ == "__main__":
    main()
