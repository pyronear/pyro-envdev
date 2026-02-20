#!/usr/bin/env python3
"""Send one update_last_image call per camera using a random image from its site folder."""

from __future__ import annotations

import argparse
import io
import json
import os
import random
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "For each camera in credentials.json, infer site name (e.g. valbonne-demo-01 -> valbonne), "
            "pick one random image from force06-demo/data/<site>/images, and send update_last_image."
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
        help="Base data directory containing <site>/images folders (default: force06-demo/data).",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=os.environ.get("API_URL", "https://alertapi.pyronear.org"),
        help="Pyro API base URL (default: API_URL env var or https://api.pyronear.org).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducible image selection.",
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


def list_site_images(data_dir: Path, site: str) -> list[Path]:
    images_dir = data_dir / site / "images"
    if not images_dir.is_dir():
        return []
    return sorted(
        [
            p
            for p in images_dir.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        ],
        key=lambda p: p.name.lower(),
    )


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
    rng = random.Random(args.seed)

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
    skipped_missing_token = 0
    skipped_unknown_site = 0
    skipped_missing_images = 0
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

        images = list_site_images(args.data_dir, site)
        if len(images) == 0:
            skipped_missing_images += 1
            print(f"[SKIP] {cam_name} (id={cam_id}) no images found in {args.data_dir / site / 'images'}")
            continue

        selected_image = rng.choice(images)
        if args.dry_run:
            sent += 1
            print(f"[DRY-RUN] {cam_name} (id={cam_id}) site={site} image={selected_image}")
            continue

        try:
            payload = load_image_payload(selected_image)
            # Same API method used in Engine.predict periodic upload path:
            # self.api_client[ip].update_last_image(stream.getvalue())
            response = pyro_client.Client(token.strip(), args.api_url).update_last_image(payload)  # type: ignore[union-attr]
            if response.status_code // 100 == 2:
                sent += 1
                print(
                    f"[OK] {cam_name} (id={cam_id}) site={site} "
                    f"image={selected_image.name} status={response.status_code}"
                )
            else:
                failed += 1
                print(
                    f"[FAIL] {cam_name} (id={cam_id}) site={site} "
                    f"image={selected_image.name} status={response.status_code}"
                )
        except Exception as exc:
            failed += 1
            print(f"[ERROR] {cam_name} (id={cam_id}) site={site} image={selected_image.name} {exc}")

    print("\nSummary")
    print(f"- API URL: {args.api_url}")
    print(f"- Cameras in file: {total}")
    print(f"- Updated last image (or would update with --dry-run): {sent}")
    print(f"- Skipped (missing token): {skipped_missing_token}")
    print(f"- Skipped (unknown site): {skipped_unknown_site}")
    print(f"- Skipped (missing images): {skipped_missing_images}")
    print(f"- Failed: {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
