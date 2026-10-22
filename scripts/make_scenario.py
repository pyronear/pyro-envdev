"""Write the frames of one fake camera from a replayed alert zip and clear images.

    python scripts/make_scenario.py data/scenarios/smoke-then-clear/croix-augas-01 \
        --alert data/replay_alerts/alert_49767.zip --frames 40 --clear clean/40-xxx.jpg

Frames are written as 000.jpg, 001.jpg, ... in time order: the alert frames of
the camera named like the output folder, then the clear images. Without
--alert only the clear images are written (a camera that never sees smoke).
The scenario.json next to the camera folders is written by hand.
"""

import argparse
import json
import zipfile
from pathlib import Path


def alert_frames(alert_zip, camera_name, count):
    zf = zipfile.ZipFile(alert_zip)
    alert = json.loads(zf.read("alert.json"))
    camera_id = next(
        k for k, cam in alert["cameras"].items() if cam["name"] == camera_name
    )
    sequence = next(s for s in alert["sequences"] if str(s["camera_id"]) == camera_id)
    detections = sorted(sequence["detections"], key=lambda d: d["recorded_at"])[:count]
    return [zf.read(d["image"]) for d in detections]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "out", type=Path, help="data/scenarios/<scenario>/<camera name>"
    )
    parser.add_argument("--alert", type=Path, help="alert zip from `make fetch-alerts`")
    parser.add_argument(
        "--frames", type=int, default=40, help="alert frames to keep (default 40)"
    )
    parser.add_argument(
        "--clear",
        type=Path,
        nargs="*",
        default=[],
        help="clear images appended at the end",
    )
    args = parser.parse_args()

    frames = alert_frames(args.alert, args.out.name, args.frames) if args.alert else []
    frames += [path.read_bytes() for path in args.clear]
    args.out.mkdir(parents=True, exist_ok=True)
    for i, data in enumerate(frames):
        (args.out / f"{i:03d}.jpg").write_bytes(data)
    print(f"{len(frames)} frames written to {args.out}")


if __name__ == "__main__":
    main()
