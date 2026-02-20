#!/usr/bin/env python3
"""Send one detection alert per camera using random image/label pairs by site."""

from __future__ import annotations

import argparse
import io
import json
import os
import time
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "For each camera in credentials.json, infer site name (e.g. valbonne-demo-01 -> valbonne), "
            "pick one random image+label pair from force06-demo/data/<site>, and send create_detection."
        )
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path(__file__).with_name("credentials.json"),
        help="Path to credentials JSON (default: force06-demo/credentials.json).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).with_name("data"),
        help="Base data directory containing <site>/images and <site>/labels (default: force06-demo/data).",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=os.environ.get("API_URL", "https://alertapi.pyronear.org"),
        help="Pyro API base URL (default: API_URL env var or https://api.pyronear.org).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=30.0,
        help="Delay in seconds between two alert sends (default: 30).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be sent without calling the API.",
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


def infer_site(cam_key: str, cam_data: dict[str, Any]) -> str | None:
    candidates = [cam_data.get("name"), cam_key]

    for value in candidates:
        if not isinstance(value, str):
            continue
        raw = value.strip().lower()
        if not raw:
            continue
        if "-demo-" in raw:
            return raw.split("-demo-", 1)[0]
        if "-" in raw:
            return raw.split("-", 1)[0]
        return raw

    bbox_mask_url = cam_data.get("bbox_mask_url")
    if isinstance(bbox_mask_url, str) and bbox_mask_url.strip():
        return bbox_mask_url.rstrip("/").split("/")[-1].lower()

    return None


def infer_azimuth(cam_data: dict[str, Any]) -> int:
    azimuths = cam_data.get("azimuths")
    if isinstance(azimuths, list) and len(azimuths) > 0:
        try:
            return int(azimuths[0])
        except (TypeError, ValueError):
            pass

    azimuth = cam_data.get("azimuth")
    try:
        return int(azimuth)
    except (TypeError, ValueError):
        return 0


def list_image_label_pairs(data_dir: Path, site: str) -> list[tuple[Path, Path]]:
    images_dir = data_dir / site / "images"
    labels_dir = data_dir / site / "labels"
    if not images_dir.is_dir() or not labels_dir.is_dir():
        return []

    image_map = {
        p.stem: p for p in images_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    }
    label_map = {p.stem: p for p in labels_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt"}

    common_stems = sorted(set(image_map).intersection(label_map))
    return [(image_map[stem], label_map[stem]) for stem in common_stems]


def parse_yolo_label_file(path: Path) -> list[tuple[float, float, float, float, float]]:
    bboxes: list[tuple[float, float, float, float, float]] = []

    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) < 5:
                continue

            # Expected demo label format: class cx cy w h conf
            try:
                if len(parts) >= 6:
                    cx = float(parts[1])
                    cy = float(parts[2])
                    w = float(parts[3])
                    h = float(parts[4])
                    conf = float(parts[5])
                else:
                    cx = float(parts[1])
                    cy = float(parts[2])
                    w = float(parts[3])
                    h = float(parts[4])
                    conf = 1.0
            except ValueError:
                continue

            x1 = max(0.0, min(1.0, cx - w / 2.0))
            y1 = max(0.0, min(1.0, cy - h / 2.0))
            x2 = max(0.0, min(1.0, cx + w / 2.0))
            y2 = max(0.0, min(1.0, cy + h / 2.0))
            bboxes.append((x1, y1, x2, y2, conf))

    return bboxes


def load_image_payload(image_path: Path) -> bytes:
    """Return image bytes, preferring Engine-like JPEG stream when Pillow is available."""
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return image_path.read_bytes()

    stream = io.BytesIO()
    with Image.open(image_path) as img:  # type: ignore[attr-defined]
        img.convert("RGB").save(stream, format="JPEG")
    return stream.getvalue()


def main() -> int:
    args = parse_args()

    try:
        credentials = load_credentials(args.credentials)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    pyro_client = None
    if not args.dry_run:
        try:
            from pyroclient import client as pyro_client  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            print("[ERROR] Missing dependency: pyroclient")
            print("Install project dependencies first, then run this script again.")
            return 1

    total = len(credentials)
    sent = 0
    total_pairs_found = 0
    api_calls_attempted = 0
    skipped_missing_token = 0
    skipped_unknown_site = 0
    skipped_missing_pairs = 0
    skipped_empty_bboxes = 0
    failed = 0

    for cam_key in sorted(credentials):
        cam_data = credentials[cam_key]
        cam_name = str(cam_data.get("name") or cam_key)
        cam_id = str(cam_data.get("id") or "unknown")
        token = cam_data.get("token")

        if not isinstance(token, str) or not token.strip():
            skipped_missing_token += 1
            print(f"[SKIP] {cam_name} (id={cam_id}) missing token")
            continue

        site = infer_site(cam_key, cam_data)
        if not isinstance(site, str) or not site:
            skipped_unknown_site += 1
            print(f"[SKIP] {cam_name} (id={cam_id}) cannot infer site")
            continue

        pairs = list_image_label_pairs(args.data_dir, site)
        if len(pairs) == 0:
            skipped_missing_pairs += 1
            print(
                f"[SKIP] {cam_name} (id={cam_id}) no image/label pairs in "
                f"{args.data_dir / site / 'images'} and {args.data_dir / site / 'labels'}"
            )
            continue

        total_pairs_found += len(pairs)
        cam_azimuth = infer_azimuth(cam_data)
        for idx, (image_path, label_path) in enumerate(pairs, start=1):
            bboxes = parse_yolo_label_file(label_path)
            if len(bboxes) == 0:
                skipped_empty_bboxes += 1
                print(f"[SKIP] {cam_name} (id={cam_id}) empty/invalid label file: {label_path}")
                continue

            if args.dry_run:
                sent += 1
                print(
                    f"[DRY-RUN] {cam_name} (id={cam_id}) site={site} azimuth={cam_azimuth} "
                    f"[{idx}/{len(pairs)}] image={image_path} label={label_path.name} bboxes={len(bboxes)}"
                )
                continue

            try:
                if api_calls_attempted > 0 and args.sleep_seconds > 0:
                    print(f"[WAIT] Sleeping {args.sleep_seconds:.1f}s before next alert")
                    time.sleep(args.sleep_seconds)

                payload = load_image_payload(image_path)
                api_calls_attempted += 1
                # Same call path as Engine._process_alerts:
                # self.api_client[ip].create_detection(stream.getvalue(), cam_azimuth, bboxes)
                response = pyro_client.Client(token.strip(), args.api_url).create_detection(  # type: ignore[union-attr]
                    payload, cam_azimuth, bboxes
                )
                if response.status_code // 100 == 2:
                    sent += 1
                    print(
                        f"[OK] {cam_name} (id={cam_id}) site={site} azimuth={cam_azimuth} "
                        f"[{idx}/{len(pairs)}] image={image_path.name} bboxes={len(bboxes)} status={response.status_code}"
                    )
                else:
                    failed += 1
                    print(
                        f"[FAIL] {cam_name} (id={cam_id}) site={site} azimuth={cam_azimuth} "
                        f"[{idx}/{len(pairs)}] image={image_path.name} bboxes={len(bboxes)} status={response.status_code}"
                    )
            except Exception as exc:
                failed += 1
                print(
                    f"[ERROR] {cam_name} (id={cam_id}) site={site} azimuth={cam_azimuth} "
                    f"[{idx}/{len(pairs)}] image={image_path.name} {exc}"
                )

    print("\nSummary")
    print(f"- API URL: {args.api_url}")
    print(f"- Delay between alerts (seconds): {args.sleep_seconds}")
    print(f"- Cameras in file: {total}")
    print(f"- Matched image/label pairs found: {total_pairs_found}")
    print(f"- Alerts sent (or would send with --dry-run): {sent}")
    print(f"- Skipped (missing token): {skipped_missing_token}")
    print(f"- Skipped (unknown site): {skipped_unknown_site}")
    print(f"- Skipped (missing image/label pairs): {skipped_missing_pairs}")
    print(f"- Skipped (empty/invalid labels): {skipped_empty_bboxes}")
    print(f"- Failed: {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
