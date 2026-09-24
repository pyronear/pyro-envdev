#!/usr/bin/env python3
"""Fetch real alerts from the production alert API, share them through a GitHub
release, and replay them on the local stack.

  fetch ALERT_ID...     download alerts to data/replay_alerts/alert_<id>.zip
                        (needs the admin DISTANT_* credentials in .env)
  publish ALERT_ID...   upload the zips to the `replay-alerts` GitHub release (needs gh)
  list                  list the alerts available in the release
  replay ALERT_ID...    replay alerts on the local API, one after the other
      --mode live       one frame per camera every --interval seconds, timestamped now
      --mode demo       post everything at once, timestamped today at the original
                        time of day (--date today) or as in prod (--date original)

Examples:
  python3 scripts/replay_alerts.py fetch 54095
  python3 scripts/replay_alerts.py publish 54095
  python3 scripts/replay_alerts.py replay 54095 --mode demo
"""

import argparse
import ast
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from itertools import zip_longest
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
ALERTS_DIR = REPO_ROOT / "data" / "replay_alerts"
GITHUB_REPO = "pyronear/pyro-envdev"
RELEASE_TAG = "replay-alerts"
CAMERA_FIELDS = ("name", "angle_of_view", "elevation", "lat", "lon")


def login(api_url, username, password):
    r = requests.post(
        f"{api_url}/api/v1/login/creds",
        data={"username": username, "password": password},
        timeout=30,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def get(api_url, path, headers, **params):
    r = requests.get(f"{api_url}{path}", headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def zip_path(alert_id):
    return ALERTS_DIR / f"alert_{alert_id}.zip"


# -------------------------------------------------------------------
# fetch / publish / list
# -------------------------------------------------------------------


def fetch(alert_ids):
    api_url = os.environ["DISTANT_API_URL"].rstrip("/")
    headers = login(
        api_url,
        os.environ["DISTANT_ALERT_API_LOGIN"],
        os.environ["DISTANT_ALERT_API_PASSWORD"],
    )
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    for alert_id in alert_ids:
        alert = get(api_url, f"/api/v1/alerts/{alert_id}", headers)
        sequences = get(
            api_url, f"/api/v1/alerts/{alert_id}/sequences", headers, limit=100
        )
        cameras = {}
        with zipfile.ZipFile(zip_path(alert_id), "w") as zf:
            for seq in sequences:
                cam_id = seq["camera_id"]
                if cam_id not in cameras:
                    cam = get(api_url, f"/api/v1/cameras/{cam_id}", headers)
                    cameras[cam_id] = {k: cam[k] for k in CAMERA_FIELDS}
                seq["detections"] = []
                offset = 0
                while True:
                    page = get(
                        api_url,
                        f"/api/v1/sequences/{seq['id']}/detections",
                        headers,
                        limit=100,
                        offset=offset,
                        desc=False,
                    )
                    for det in page:
                        image = f"images/{det['bucket_key']}"
                        if image not in zf.namelist():
                            img = requests.get(det["url"], timeout=60)
                            img.raise_for_status()
                            zf.writestr(image, img.content)
                        seq["detections"].append(
                            {
                                "recorded_at": det["recorded_at"],
                                "bbox": det["bbox"],
                                "others_bboxes": det["others_bboxes"],
                                "image": image,
                            }
                        )
                    if len(page) < 100:
                        break
                    offset += 100
            alert["sequences"] = sequences
            alert["cameras"] = cameras
            zf.writestr("alert.json", json.dumps(alert, indent=1))
        n_dets = sum(len(s["detections"]) for s in sequences)
        print(
            f"alert {alert_id}: {len(sequences)} sequences, {n_dets} detections, "
            f"{len(cameras)} cameras -> {zip_path(alert_id)}"
        )


def publish(alert_ids):
    files = [str(zip_path(a)) for a in alert_ids]
    missing = [f for f in files if not Path(f).is_file()]
    if missing:
        sys.exit(f"missing {missing}, run `fetch` first")
    gh = ["gh", "release", "-R", GITHUB_REPO]
    if subprocess.run([*gh, "view", RELEASE_TAG], capture_output=True).returncode:
        notes = "Real alerts for scripts/replay_alerts.py"
        subprocess.run(
            [*gh, "create", RELEASE_TAG, "--title", "Replay alerts", "--notes", notes],
            check=True,
        )
    subprocess.run([*gh, "upload", RELEASE_TAG, *files, "--clobber"], check=True)


def list_alerts():
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{RELEASE_TAG}",
        timeout=30,
    )
    r.raise_for_status()
    for asset in r.json()["assets"]:
        print(asset["name"].removeprefix("alert_").removesuffix(".zip"))


# -------------------------------------------------------------------
# replay
# -------------------------------------------------------------------


def parse_bboxes(s):
    """Parse a stored bbox string, dropping degenerate boxes the API rejects."""
    boxes = ast.literal_eval(s) if s else []
    return [
        tuple(b)
        for b in boxes
        if round(b[0], 3) < round(b[2], 3) and round(b[1], 3) < round(b[3], 3)
    ]


def fmt_bboxes(boxes):
    # The API accepts `0`, `1` or `0.xxx` only, never `1.0` or `0.0`.
    def fmt(x):
        return f"{round(float(x), 3):.3f}".rstrip("0").rstrip(".") or "0"

    return "[" + ",".join("(" + ",".join(map(fmt, b)) + ")" for b in boxes) + "]"


def build_rounds(alert):
    """Group detections into frames (one per uploaded image) and interleave cameras.

    A prod upload with several boxes yields one detection per box plus continuity
    rows, all sharing the image: they are replayed as a single upload. Round k holds
    the k-th frame of every (camera, azimuth) stream, like parallel real cameras.
    """
    frames = {}
    for seq in alert["sequences"]:
        stream = (seq["camera_id"], seq["camera_azimuth"])
        for det in seq["detections"]:
            frame = frames.setdefault(
                det["image"],
                {"stream": stream, "image": det["image"], "boxes": []},
            )
            frame["recorded_at"] = datetime.fromisoformat(det["recorded_at"])
            for box in parse_bboxes(det["bbox"]) + parse_bboxes(det["others_bboxes"]):
                if box not in frame["boxes"]:
                    frame["boxes"].append(box)
    streams = {}
    for frame in sorted(frames.values(), key=lambda f: f["recorded_at"]):
        streams.setdefault(frame["stream"], []).append(frame)
    return [[f for f in r if f] for r in zip_longest(*streams.values())]


def day_offset(rounds, when):
    """Shift to apply to recorded_at: whole days, so all frames move together."""
    if when == "original":
        return timedelta(0)
    first = min(f["recorded_at"] for r in rounds for f in r)
    return timedelta(days=(date.today() - first.date()).days)


def load_alert(alert_id):
    path = zip_path(alert_id)
    if not path.is_file():
        url = f"https://github.com/{GITHUB_REPO}/releases/download/{RELEASE_TAG}/{path.name}"
        print(f"downloading {url}")
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        ALERTS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    zf = zipfile.ZipFile(path)
    return zf, json.loads(zf.read("alert.json"))


def replay_alert(alert_id, args, admin):
    zf, alert = load_alert(alert_id)
    rounds = build_rounds(alert)
    offset = day_offset(rounds, args.date)
    last = max(f["recorded_at"] for r in rounds for f in r) + offset
    if args.mode == "demo" and last > datetime.now(timezone.utc).replace(tzinfo=None):
        print(f"warning: alert {alert_id} ends at {last} UTC, later than now")

    api = args.api_url
    local_cams = {c["name"]: c["id"] for c in get(api, "/api/v1/cameras/", admin)}
    tokens, poses = {}, {}
    for prod_id, cam in alert["cameras"].items():
        name = cam["name"]
        if name not in local_cams:
            payload = {**cam, "organization_id": args.org_id, "is_trustable": True}
            r = requests.post(
                f"{api}/api/v1/cameras/", headers=admin, json=payload, timeout=30
            )
            r.raise_for_status()
            local_cams[name] = r.json()["id"]
            print(f"created camera {name} (id {local_cams[name]})")
        r = requests.post(
            f"{api}/api/v1/cameras/{local_cams[name]}/token", headers=admin, timeout=30
        )
        r.raise_for_status()
        tokens[int(prod_id)] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    # A fresh pose per stream keeps this replay apart from earlier ones.
    for prod_cam_id, azimuth in {f["stream"] for r in rounds for f in r}:
        name = alert["cameras"][str(prod_cam_id)]["name"]
        payload = {"camera_id": local_cams[name], "azimuth": azimuth}
        r = requests.post(
            f"{api}/api/v1/poses/", headers=admin, json=payload, timeout=30
        )
        r.raise_for_status()
        poses[(prod_cam_id, azimuth)] = r.json()["id"]

    print(f"alert {alert_id}: replaying {len(rounds)} rounds ({args.mode} mode)")
    for i, frames in enumerate(rounds):
        for f in frames:
            data = {"bboxes": fmt_bboxes(f["boxes"]), "pose_id": poses[f["stream"]]}
            if args.mode == "demo":
                data["recorded_at"] = (f["recorded_at"] + offset).isoformat()
            r = requests.post(
                f"{api}/api/v1/detections/",
                headers=tokens[f["stream"][0]],
                data=data,
                files={"file": ("frame.jpg", zf.read(f["image"]), "image/jpeg")},
                timeout=60,
            )
            if r.status_code not in (201, 204):
                print(f"  error on {f['image']}: {r.status_code} {r.text[:200]}")
        print(f"  round {i + 1}/{len(rounds)} sent ({len(frames)} frames)")
        if args.mode == "live" and i + 1 < len(rounds):
            time.sleep(args.interval)


def replay(args):
    admin = login(
        args.api_url, os.environ["SUPERADMIN_LOGIN"], os.environ["SUPERADMIN_PWD"]
    )
    for alert_id in args.alert_ids:
        replay_alert(alert_id, args, admin)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("fetch", "publish"):
        sub.add_parser(cmd).add_argument("alert_ids", nargs="+", type=int)
    sub.add_parser("list")
    p = sub.add_parser("replay")
    p.add_argument("alert_ids", nargs="+", type=int)
    p.add_argument("--mode", choices=("live", "demo"), default="demo")
    p.add_argument("--date", choices=("today", "original"), default="today")
    p.add_argument("--interval", type=float, default=30, help="live mode, seconds")
    p.add_argument("--api-url", default="http://localhost:5050")
    p.add_argument("--org-id", type=int, default=2, help="org of created cameras")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    if args.cmd == "fetch":
        fetch(args.alert_ids)
    elif args.cmd == "publish":
        publish(args.alert_ids)
    elif args.cmd == "list":
        list_alerts()
    else:
        replay(args)


if __name__ == "__main__":
    main()
