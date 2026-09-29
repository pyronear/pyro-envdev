#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["requests", "python-dotenv", "boto3", "psycopg[binary]"]
# ///
"""Fetch real alerts from the production alert API, share them through a GitHub
release, and replay them on the local stack.

  fetch ALERT_ID...     download alerts to data/replay_alerts/alert_<id>.zip
                        (needs the admin DISTANT_* credentials in .env)
  publish ALERT_ID...   upload the zips to the `replay-alerts` GitHub release (needs gh)
  list                  list the alerts available in the release
  replay ALERT_ID...    replay alerts on the local stack, one after the other
      --mode demo       copy the prod alert as is (images to the bucket, rows into the
                        DB), shifted as a block: the first sequence starts at --start
                        (local time), or by default the latest one starts 1 hour ago
      --mode live       post one frame per camera every --interval seconds through the
                        API, timestamped now: validation and triangulation run locally

Examples:
  uv run scripts/replay_alerts.py fetch 54095
  uv run scripts/replay_alerts.py publish 54095
  uv run scripts/replay_alerts.py replay 54095 --mode demo
"""

import argparse
import ast
import json
import os
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from itertools import zip_longest
from pathlib import Path

import boto3
import psycopg
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


def download(zf, name, url):
    if name not in zf.namelist():
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        zf.writestr(name, r.content)


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
        # Written to a temp file so a failed fetch never leaves a broken zip behind.
        tmp = zip_path(alert_id).with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w") as zf:
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
                        download(zf, image, det["url"])
                        crop = None
                        if det["crop_bucket_key"]:
                            # Detection lists return crop_url=null, only /url signs it.
                            crop = f"crops/{det['crop_bucket_key']}"
                            urls = get(
                                api_url, f"/api/v1/detections/{det['id']}/url", headers
                            )
                            download(zf, crop, urls["crop_url"])
                        seq["detections"].append(
                            {
                                "recorded_at": det["recorded_at"],
                                "bbox": det["bbox"],
                                "others_bboxes": det["others_bboxes"],
                                "image": image,
                                "crop": crop,
                            }
                        )
                    if len(page) < 100:
                        break
                    offset += 100
            alert["sequences"] = sequences
            alert["cameras"] = cameras
            zf.writestr("alert.json", json.dumps(alert, indent=1))
        tmp.replace(zip_path(alert_id))
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
            [
                *gh,
                "create",
                RELEASE_TAG,
                "--title",
                "Replay alerts",
                "--notes",
                notes,
                "--latest=false",
            ],
            check=True,
        )
    subprocess.run([*gh, "upload", RELEASE_TAG, *files, "--clobber"], check=True)


def list_alerts():
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{RELEASE_TAG}",
        timeout=30,
    )
    if r.status_code == 404:
        print("no alerts published")
        return
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
    Only the alert's own boxes are replayed: `others_bboxes` belong to sequences
    outside the alert, which prod may have rejected but the local stack would
    validate (no temporal model) into extra alerts.
    """
    frames = {}
    for seq in alert["sequences"]:
        stream = (seq["camera_id"], seq["camera_azimuth"])
        for det in seq["detections"]:
            frame = frames.setdefault(
                det["image"],
                {"stream": stream, "image": det["image"], "boxes": [], "crops": {}},
            )
            frame["recorded_at"] = datetime.fromisoformat(det["recorded_at"])
            own = parse_bboxes(det["bbox"])
            for box in own:
                if box not in frame["boxes"]:
                    frame["boxes"].append(box)
            # A prod detection holds one box and the crop of that box.
            if det.get("crop") and len(own) == 1:
                frame["crops"][own[0]] = det["crop"]
    streams = {}
    for frame in sorted(frames.values(), key=lambda f: f["recorded_at"]):
        streams.setdefault(frame["stream"], []).append(frame)
    return [[f for f in r if f] for r in zip_longest(*streams.values())]


def utc_start(s):
    """--start value: local time (naive) or with offset, returned as naive UTC."""
    return datetime.fromisoformat(s).astimezone(timezone.utc).replace(tzinfo=None)


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


def setup_cameras(alert, streams, args, admin):
    """Find or create the alert's cameras locally, then a fresh pose per stream.

    Returns {prod camera id: local camera}, {stream: local pose id}.
    """
    api = args.api_url
    local_cams = {c["name"]: c for c in get(api, "/api/v1/cameras/", admin)}
    cams = {}
    for prod_id, cam in alert["cameras"].items():
        name = cam["name"]
        if name not in local_cams:
            payload = {**cam, "organization_id": args.org_id, "is_trustable": True}
            r = requests.post(
                f"{api}/api/v1/cameras/", headers=admin, json=payload, timeout=30
            )
            r.raise_for_status()
            local_cams[name] = r.json()
            print(f"created camera {name} (id {local_cams[name]['id']})")
        cams[int(prod_id)] = local_cams[name]
    # Images are stored and served per organization bucket: one org per alert.
    orgs = {c["name"]: c["organization_id"] for c in cams.values()}
    if len(set(orgs.values())) > 1:
        sys.exit(f"alert cameras span several organizations: {orgs}")
    # A fresh pose per stream keeps this replay apart from earlier ones.
    poses = {}
    for prod_cam_id, azimuth in streams:
        payload = {"camera_id": cams[prod_cam_id]["id"], "azimuth": azimuth}
        r = requests.post(
            f"{api}/api/v1/poses/", headers=admin, json=payload, timeout=30
        )
        r.raise_for_status()
        poses[(prod_cam_id, azimuth)] = r.json()["id"]
    return cams, poses


def replay_live(alert_id, args, admin):
    """Post frames through the API, timestamped now: exercises the whole pipeline."""
    zf, alert = load_alert(alert_id)
    rounds = build_rounds(alert)
    cams, poses = setup_cameras(
        alert, {f["stream"] for r in rounds for f in r}, args, admin
    )
    tokens = {}
    for prod_id, cam in cams.items():
        r = requests.post(
            f"{args.api_url}/api/v1/cameras/{cam['id']}/token",
            headers=admin,
            timeout=30,
        )
        r.raise_for_status()
        tokens[prod_id] = {"Authorization": f"Bearer {r.json()['access_token']}"}

    print(f"alert {alert_id}: replaying {len(rounds)} rounds (live mode)")
    failures = 0
    for i, frames in enumerate(rounds):
        for f in frames:
            data = {"bboxes": fmt_bboxes(f["boxes"]), "pose_id": poses[f["stream"]]}
            files = [("file", ("frame.jpg", zf.read(f["image"]), "image/jpeg"))]
            # The API wants one crop per box, in the same order, or none at all.
            crops = [f["crops"].get(b) for b in f["boxes"]]
            if crops and all(crops):
                files += [
                    ("crop", ("crop.jpg", zf.read(c), "image/jpeg")) for c in crops
                ]
            r = requests.post(
                f"{args.api_url}/api/v1/detections/",
                headers=tokens[f["stream"][0]],
                data=data,
                files=files,
                timeout=60,
            )
            if r.status_code not in (201, 204):
                failures += 1
                print(f"  error on {f['image']}: {r.status_code} {r.text[:200]}")
        print(f"  round {i + 1}/{len(rounds)} sent ({len(frames)} frames)")
        if i + 1 < len(rounds):
            time.sleep(args.interval)
    return failures


def replay_demo(alert_id, args, admin):
    """Copy the prod alert as is: images to the org bucket, rows straight into the DB.

    No validation, triangulation nor merge runs: the alert keeps its prod sequences and
    location, and never mixes with other replays. Tied to the pyro-api DB schema.
    """
    zf, alert = load_alert(alert_id)
    seqs = alert["sequences"]
    started = [datetime.fromisoformat(s["started_at"]) for s in seqs]
    # One shift for all rows keeps the prod timeline. Default: the latest sequence
    # starts 1 hour ago.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    offset = (
        args.start - min(started)
        if args.start
        else now - timedelta(hours=1) - max(started)
    )
    streams = {(s["camera_id"], s["camera_azimuth"]) for s in seqs}
    cams, poses = setup_cameras(alert, streams, args, admin)
    org_id = next(iter(cams.values()))["organization_id"]

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_PROXY_URL") or "http://localhost:9000",
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name=os.environ.get("S3_REGION"),
    )
    bucket = f"{os.environ['SERVER_NAME']}-alert-api-{org_id}"
    # Keys unique to this replay: the API deletes a crop along with its detection, so
    # replays must not share objects, and a failed replay can drop its own safely.
    tag = uuid.uuid4().hex[:8]
    keys = {
        name: f"replay-{tag}-{Path(name).name}"
        for s in seqs
        for d in s["detections"]
        for name in (d["image"], d.get("crop"))
        if name
    }
    uploaded = []
    try:
        for name, key in keys.items():
            s3.put_object(Bucket=bucket, Key=key, Body=zf.read(name))
            uploaded.append(key)
        alert_id_local = insert_alert(alert, cams, poses, org_id, keys, offset)
    except BaseException:
        for key in uploaded:
            s3.delete_object(Bucket=bucket, Key=key)
        raise
    n_dets = sum(len(s["detections"]) for s in seqs)
    print(
        f"alert {alert_id} -> local alert {alert_id_local}: {len(seqs)} sequences, "
        f"{n_dets} detections, {len(keys)} images and crops, "
        f"starting {min(started) + offset} UTC"
    )
    return 0


def insert_alert(alert, cams, poses, org_id, keys, offset):
    """Write the alert, its sequences and detections in one transaction."""

    def shift(ts):
        return datetime.fromisoformat(ts) + offset

    seqs = alert["sequences"]
    dsn = (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@localhost:5432/{os.environ['POSTGRES_DB']}"
    )
    with psycopg.connect(dsn) as conn:  # one transaction, rolled back on error
        alert_id_local = conn.execute(
            "INSERT INTO alerts (organization_id, lat, lon, started_at, last_seen_at)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (
                org_id,
                alert["lat"],
                alert["lon"],
                shift(alert["started_at"]),
                shift(alert["last_seen_at"]),
            ),
        ).fetchone()[0]
        for s in seqs:
            cam_id = cams[s["camera_id"]]["id"]
            pose_id = poses[(s["camera_id"], s["camera_azimuth"])]
            seq_id = conn.execute(
                # is_wildfire is left unset: the prod label came afterwards, and a
                # labeled alert is not listed as live in the frontend.
                "INSERT INTO sequences (camera_id, pose_id, camera_azimuth,"
                " sequence_azimuth, cone_angle, started_at, last_seen_at, max_conf,"
                " temporal_model_score, temporal_model_version, temporal_api_version,"
                " is_validated) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " RETURNING id",
                (
                    cam_id,
                    pose_id,
                    s["camera_azimuth"],
                    s["sequence_azimuth"],
                    s["cone_angle"],
                    shift(s["started_at"]),
                    shift(s["last_seen_at"]),
                    s.get("max_conf"),
                    s.get("temporal_model_score"),
                    s.get("temporal_model_version"),
                    s.get("temporal_api_version"),
                    s["is_validated"],
                ),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO alerts_sequences (alert_id, sequence_id) VALUES (%s, %s)",
                (alert_id_local, seq_id),
            )
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO detections (camera_id, pose_id, sequence_id, bucket_key,"
                    " crop_bucket_key, bbox, others_bboxes, created_at, recorded_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        (
                            cam_id,
                            pose_id,
                            seq_id,
                            keys[d["image"]],
                            keys.get(d.get("crop")),
                            d["bbox"],
                            d["others_bboxes"],
                            shift(d["recorded_at"]),
                            shift(d["recorded_at"]),
                        )
                        for d in s["detections"]
                    ],
                )
    return alert_id_local


def replay(args):
    admin = login(
        args.api_url, os.environ["SUPERADMIN_LOGIN"], os.environ["SUPERADMIN_PWD"]
    )
    run = replay_demo if args.mode == "demo" else replay_live
    failures = sum(run(a, args, admin) for a in args.alert_ids)
    if failures:
        sys.exit(f"{failures} detection uploads failed")


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
    p.add_argument(
        "--start",
        type=utc_start,
        help="demo mode, first frame time, e.g. 2026-07-10T18:53",
    )
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
