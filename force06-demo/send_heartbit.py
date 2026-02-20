#!/usr/bin/env python3
"""Send one heartbeat per camera listed in a credentials JSON file."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read camera credentials and send one heartbeat per camera token. "
            "Uses the same API client call as Engine.heartbeat()."
        )
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path(__file__).with_name("credentials.json"),
        help="Path to credentials JSON (default: force06-demo/credentials.json).",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=os.environ.get("API_URL", "https://alertapi.pyronear.org"),
        help="Pyro API base URL (default: API_URL env var or https://api.pyronear.org).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which cameras would be pinged without sending requests.",
    )
    return parser.parse_args()


def load_credentials(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Credentials file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Credentials file must contain a JSON object at top-level.")

    for key, value in data.items():
        if not isinstance(value, dict):
            raise ValueError(f"Camera entry '{key}' must be a JSON object.")

    return data


def main() -> int:
    args = parse_args()

    try:
        credentials = load_credentials(args.credentials)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    total = len(credentials)
    sent = 0
    skipped_missing_token = 0
    failed = 0

    pyro_client = None
    if not args.dry_run:
        try:
            from pyroclient import client as pyro_client  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            print("[ERROR] Missing dependency: pyroclient")
            print("Install project dependencies first, then run this script again.")
            return 1

    for cam_key in sorted(credentials):
        cam_data = credentials[cam_key]
        cam_name = str(cam_data.get("name") or cam_key)
        cam_id = str(cam_data.get("id") or "unknown")
        token = cam_data.get("token")

        if not isinstance(token, str) or not token.strip():
            skipped_missing_token += 1
            print(f"[SKIP] {cam_name} (id={cam_id}) missing token")
            continue

        if args.dry_run:
            sent += 1
            print(f"[DRY-RUN] would send heartbeat for {cam_name} (id={cam_id})")
            continue

        try:
            # Same mechanism as in Engine: client.Client(token, api_url).heartbeat()
            response = pyro_client.Client(token.strip(), args.api_url).heartbeat()  # type: ignore[union-attr]
            if response.status_code // 100 == 2:
                sent += 1
                print(f"[OK] {cam_name} (id={cam_id}) status={response.status_code}")
            else:
                failed += 1
                print(f"[FAIL] {cam_name} (id={cam_id}) status={response.status_code}")
        except Exception as exc:
            failed += 1
            print(f"[ERROR] {cam_name} (id={cam_id}) {exc}")

    print("\nSummary")
    print(f"- API URL: {args.api_url}")
    print(f"- Cameras in file: {total}")
    print(f"- Heartbeats sent (or would send with --dry-run): {sent}")
    print(f"- Skipped (missing token): {skipped_missing_token}")
    print(f"- Failed: {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
