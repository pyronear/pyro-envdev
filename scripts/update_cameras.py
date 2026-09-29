#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["requests", "python-dotenv", "boto3", "psycopg[binary]"]
# ///
"""Refresh the local cameras seen in the replay alerts: prod setup, last image, ping.

For each camera of the given alerts (default: every published alert), set its prod
position, elevation and poses, upload its most recent image from the alerts as the
camera's last image, then send a heartbeat, as a real camera would. Missing cameras
are created like in replay_alerts.py.

Examples:
  uv run scripts/update_cameras.py
  uv run scripts/update_cameras.py 49767
"""

import argparse
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from replay_alerts import (
    REPO_ROOT,
    camera_token,
    load_alert,
    login,
    published_alerts,
    sync_cameras,
)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("alert_ids", nargs="*", type=int)
    parser.add_argument("--api-url", default="http://localhost:5050")
    parser.add_argument("--org-id", type=int, default=2, help="org of created cameras")
    args = parser.parse_args()
    load_dotenv(REPO_ROOT / ".env")
    api = args.api_url
    admin = login(api, os.environ["SUPERADMIN_LOGIN"], os.environ["SUPERADMIN_PWD"])

    # Latest image of each camera across the alerts:
    # {name: (recorded_at, zip, image path, local camera id)}
    latest = {}
    for alert_id in args.alert_ids or published_alerts():
        zf, alert = load_alert(alert_id)
        cams, _ = sync_cameras(alert, args, admin)
        for s in alert["sequences"]:
            cam = cams[s["camera_id"]]
            for d in s["detections"]:
                if d["recorded_at"] > latest.get(cam["name"], ("",))[0]:
                    latest[cam["name"]] = (d["recorded_at"], zf, d["image"], cam["id"])

    for name, (recorded_at, zf, image, cam_id) in sorted(latest.items()):
        token = camera_token(api, cam_id, admin)
        r = requests.patch(
            f"{api}/api/v1/cameras/image",
            headers=token,
            files={"file": (Path(image).name, zf.read(image), "image/jpeg")},
            timeout=60,
        )
        r.raise_for_status()
        r = requests.patch(f"{api}/api/v1/cameras/heartbeat", headers=token, timeout=30)
        r.raise_for_status()
        print(f"{name}: last image from {recorded_at}, pinged")


if __name__ == "__main__":
    main()
