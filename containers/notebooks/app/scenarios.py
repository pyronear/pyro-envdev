"""Send realistic demo alerts to the dev API.

Each scenario replays real wildfire footage with the camera that recorded it, so
camera names, images and the cones drawn on the map agree. Cameras are referenced by
name, never by id (the ids in the database do not match the ids of the seed CSV).

From a notebook:
    from scenarios import run_scenario
    run_scenario("triangulated-fire-77")

From a shell, inside the notebooks container:
    python scenarios.py                          # every scenario
    python scenarios.py single-camera-fire-77    # selected scenarios
    python scenarios.py --delete-all-alerts      # start over
"""

import ast
import io
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from PIL import Image
from pyroclient import Client

from api import get_camera_token, get_token
from utils import dl_seqs_from_url, get_or_create_pose_id_for_azimuth

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")
API_URL = os.environ.get("API_URL", "http://api:5050")

RELEASE_URL = "https://github.com/pyronear/pyro-envdev/releases/download/v0.0.1"
# local folder -> archive of the v0.0.1 release
SAMPLES = {
    HERE.parent / "data" / "alert_samples": f"{RELEASE_URL}/alert_samples.zip",
    HERE / "selection-true-positives": f"{RELEASE_URL}/selection-true-positives.zip",
}
TRIANGULATED = HERE.parent / "data" / "alert_samples" / "triangulated_sequences"
SINGLE = HERE / "selection-true-positives"
# Capture time in the sample file names: 20250714112431 or 2025-05-20T11-38-20
CAPTURE_TIME = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})T?(\d{2})-?(\d{2})-?(\d{2})")
# Spacing of frames whose file name has no capture time
FRAME_INTERVAL = timedelta(seconds=30)
# Samples start with frames ~1 s apart, likely buffered frames uploaded in a burst when
# the smoke was detected: such a leading burst is spread at the typical gap.
BURST_GAP = timedelta(seconds=5)
# Smallest side of the close-up sent with each detection, in pixels
CROP_MIN_SIZE = 160
# Ground-truth labels carry no confidence: use a plausible model score so that
# boxes are displayed.
GROUND_TRUTH_CONF = 0.6

SCENARIOS = {
    "triangulated-fire-77": {
        "description": (
            "Real fire of 2025-07-14 seen by three towers: "
            "one alert, three cameras, located on the map."
        ),
        # (camera name, pose azimuth, sequence folder)
        "shots": [
            (
                "croix-augas-02",
                190,
                TRIANGULATED / "41_croix-augas-02_2025-07-14_11-24-31",
            ),
            ("nemours-02", 25, TRIANGULATED / "65_nemours-02_2025-07-14_11-24-10"),
            (
                "moret-sur-loing-01",
                280,
                TRIANGULATED / "66_moret-sur-loing-01_2025-07-14_11-22-05",
            ),
        ],
    },
    "single-camera-fire-77": {
        "description": (
            "Real fire of 2025-05-20 seen by a single camera: "
            "one alert with a direction but no location."
        ),
        # The folder name says 300, but the landscape matches the map at 120.
        "shots": [
            (
                "videlles-02",
                120,
                SINGLE / "2025-05-20T11-38-20_videlles-02-300_sequence-6438",
            )
        ],
        # Its cone crosses the 2025-07-14 fire: detach it, as an operator would.
        "standalone": True,
    },
    "single-camera-fire-07": {
        "description": (
            "Real fire of 2025-09-29 seen from Serre-de-Barre, "
            "for the sdis-07 organization."
        ),
        # Brison-03 saw it too, but its sample has a zero-confidence box and an azimuth
        # that puts the fire 600 m from Serre-de-Barre, while the image shows it several
        # km away.
        "shots": [
            (
                "serre-de-barre-01",
                173,
                TRIANGULATED / "22_serre-de-barre-01_2025-09-29_13-56-58",
            )
        ],
    },
}


def download_samples() -> None:
    """Fetch the sample sequences of the release, once."""
    for folder, url in SAMPLES.items():
        if not folder.is_dir():
            print(f"Downloading {url} ...")
            dl_seqs_from_url(url, str(folder))


def load_frames(folder: Path):
    """Return (image path, bboxes, capture time or None) for frames with a box."""
    frames = []
    for img in sorted((folder / "images").glob("*.jpg")):
        pred = folder / "labels_predictions" / f"{img.stem}.txt"
        gt = folder / "labels_ground_truth" / f"{img.stem}.txt"
        bboxes = []
        if pred.is_file() and pred.read_text().lstrip().startswith("["):
            # pyro-engine format: [(xmin, ymin, xmax, ymax, conf), ...]
            bboxes = ast.literal_eval(pred.read_text())
        elif gt.is_file():
            # YOLO format: class cx cy w h
            for line in gt.read_text().splitlines():
                _, cx, cy, w, h = map(float, line.split()[:5])
                bboxes.append(
                    (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, GROUND_TRUTH_CONF)
                )
        if bboxes:
            match = CAPTURE_TIME.search(img.stem)
            captured = datetime(*map(int, match.groups())) if match else None
            frames.append(
                (img, [tuple(round(v, 3) for v in b) for b in bboxes], captured)
            )
    if not frames:
        raise FileNotFoundError(f"No usable frames in {folder}")
    times = [t for *_, t in frames]
    if all(times):
        frames = [(i, b, t) for (i, b, _), t in zip(frames, _spread_bursts(times))]
    return frames


def _spread_bursts(times: list) -> list:
    """Spread a burst of short gaps at the start of a sequence at its typical gap.

    Sequences without a leading burst, or made of short gaps only, are kept as is.
    """
    gaps = [b - a for a, b in zip(times, times[1:])]
    burst = next((i for i, gap in enumerate(gaps) if gap >= BURST_GAP), 0)
    if not burst:
        return times
    normal = sorted(gap for gap in gaps[burst:] if gap >= BURST_GAP)
    typical = normal[len(normal) // 2]
    return [times[burst] - (burst - i) * typical for i in range(burst)] + times[burst:]


def jpeg_bytes(image) -> bytes:
    """Encode a PIL image, or the image file at this path, as JPEG."""
    if isinstance(image, Path):
        image = Image.open(image)
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=80)
    return stream.getvalue()


def crop_bytes(image, bbox) -> bytes:
    """Close-up on a box, shown by the platform: a square around it, 3 times larger."""
    width, height = image.size
    xmin, ymin, xmax, ymax = bbox[:4]
    side = max(3 * (xmax - xmin) * width, 3 * (ymax - ymin) * height, CROP_MIN_SIZE)
    cx, cy = (xmin + xmax) / 2 * width, (ymin + ymax) / 2 * height
    box = (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
    box = (max(0, box[0]), max(0, box[1]), min(width, box[2]), min(height, box[3]))
    return jpeg_bytes(image.crop(tuple(round(v) for v in box)))


def _camera_ids(headers: dict) -> dict:
    cameras = requests.get(
        urljoin(API_URL, "/api/v1/cameras/"), headers=headers, timeout=5
    ).json()
    return {cam["name"]: cam["id"] for cam in cameras}


def _unmatch(headers: dict, alert_id: int, sequence_id: int) -> None:
    requests.post(
        urljoin(API_URL, f"/api/v1/alerts/{alert_id}/sequences/{sequence_id}/unmatch"),
        headers=headers,
        timeout=5,
    ).raise_for_status()
    print(f"   sequence {sequence_id} detached from alert {alert_id}")


def _detach_from_other_fires(
    headers: dict, poses: set, timeout_seconds: float = 60
) -> None:
    """Separate the sequences of these (camera id, pose id) from other fires' alerts."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        # Sequences are attached to alerts asynchronously, once validated.
        alerts = requests.get(
            urljoin(API_URL, "/api/v1/alerts/unlabeled/latest"),
            headers=headers,
            timeout=5,
        ).json()
        sequences = [s for a in alerts for s in a["sequences"]]
        ours = {s["id"] for s in sequences if (s["camera_id"], s["pose_id"]) in poses}
        seen = {(s["camera_id"], s["pose_id"]) for s in sequences if s["id"] in ours}
        if seen >= poses or time.monotonic() > deadline:
            break
        time.sleep(2)
    for alert in alerts:
        mine = [s["id"] for s in alert["sequences"] if s["id"] in ours]
        others = [s["id"] for s in alert["sequences"] if s["id"] not in ours]
        if not mine or not others:
            continue
        elsewhere = {
            s["id"] for a in alerts if a["id"] != alert["id"] for s in a["sequences"]
        }
        # If the other fires already have their own alert, this one only exists because
        # the cones cross: give it to our fire. Otherwise our fire gets its own alert.
        detached = others if elsewhere.issuperset(others) else mine
        for sequence_id in detached:
            _unmatch(headers, alert["id"], sequence_id)


def send_sequences(shots, standalone: bool = False, sleep_seconds: float = 0.1) -> None:
    """Replay sequence folders as detections of the given cameras.

    Args:
        shots: list of (camera name, pose azimuth in degrees, sequence folder)
        standalone: keep this fire out of alerts shared with other cameras
        sleep_seconds: delay between two detections
    """
    download_samples()
    admin_token = get_token(
        API_URL, os.environ["SUPERADMIN_LOGIN"], os.environ["SUPERADMIN_PWD"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}
    camera_ids = _camera_ids(headers)
    shots_frames, poses = [], set()
    for cam_name, azimuth, folder in shots:
        if cam_name not in camera_ids:
            raise ValueError(
                f"Unknown camera {cam_name!r}, "
                f"available: {', '.join(sorted(camera_ids))}"
            )
        cam_id = camera_ids[cam_name]
        client = Client(get_camera_token(API_URL, cam_id, admin_token), API_URL)
        pose_id = get_or_create_pose_id_for_azimuth(client, cam_id, azimuth)
        poses.add((cam_id, pose_id))
        frames = load_frames(Path(folder))
        # Dashboard: show a real view of this camera and mark it as alive.
        client.update_last_image(jpeg_bytes(frames[0][0])).raise_for_status()
        client.heartbeat().raise_for_status()
        print(f"   {cam_name} (azimuth {azimuth}): {len(frames)} frames")
        shots_frames.append((client, pose_id, frames))

    # Keep the real capture times, shifted so that the last frame is captured now: the
    # alert replays the real pace of the fire, without waiting for it.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    captured = [t for *_, frames in shots_frames for *_, t in frames]
    timed = all(captured)
    shift = now - max(captured) if timed else None
    detections = []
    for client, pose_id, frames in shots_frames:
        for i, (img, bboxes, captured_at) in enumerate(frames):
            if timed:
                recorded_at = captured_at + shift
            else:
                recorded_at = now - (len(frames) - 1 - i) * FRAME_INTERVAL
            detections.append((recorded_at, client, pose_id, img, bboxes))

    for recorded_at, client, pose_id, img, bboxes in sorted(
        detections, key=lambda d: d[0]
    ):
        image = Image.open(img)
        client.create_detection(
            jpeg_bytes(image),
            bboxes,
            pose_id=pose_id,
            crops=[crop_bytes(image, bbox) for bbox in bboxes],
            recorded_at=recorded_at.isoformat(timespec="seconds"),
        ).raise_for_status()
        time.sleep(sleep_seconds)

    if standalone:
        _detach_from_other_fires(headers, poses)


def run_scenario(name: str) -> None:
    """Send the alerts of one scenario of SCENARIOS."""
    scenario = SCENARIOS[name]
    print(f"== {name}: {scenario['description']}")
    send_sequences(scenario["shots"], standalone=scenario.get("standalone", False))


def run_all() -> None:
    for name in SCENARIOS:
        run_scenario(name)


def delete_all_alerts() -> None:
    """Delete every alert, sequence and detection (with its images) of the dev API.

    Organizations, users, cameras and poses are kept.
    """
    admin_token = get_token(
        API_URL, os.environ["SUPERADMIN_LOGIN"], os.environ["SUPERADMIN_PWD"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}
    detections, page_size = [], 500
    while True:
        page = requests.get(
            urljoin(API_URL, "/api/v1/detections/"),
            headers=headers,
            params={"limit": page_size, "offset": len(detections)},
            timeout=5,
        ).json()
        detections += page
        if len(page) < page_size:
            break
    # Deleting the sequences of an alert deletes the alert itself.
    sequence_ids = {d["sequence_id"] for d in detections if d["sequence_id"]}
    for sequence_id in sequence_ids:
        requests.delete(
            urljoin(API_URL, f"/api/v1/sequences/{sequence_id}"),
            headers=headers,
            timeout=5,
        ).raise_for_status()
    for detection in detections:
        requests.delete(
            urljoin(API_URL, f"/api/v1/detections/{detection['id']}"),
            headers=headers,
            timeout=5,
        ).raise_for_status()
    print(f"Deleted {len(sequence_ids)} sequences and {len(detections)} detections.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--delete-all-alerts"]:
        delete_all_alerts()
    else:
        for scenario_name in sys.argv[1:] or SCENARIOS:
            run_scenario(scenario_name)
    print("Done.")
