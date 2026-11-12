"""Write the frames of one fake camera from a replayed alert zip and clear images.

    python scripts/make_scenario.py data/scenarios/smoke-then-clear/croix-augas-01 \
        --alert data/replay_alerts/alert_49767.zip --frames 40 --clear clean/40-xxx.jpg

Frames are written as 000.jpg, 001.jpg, ... in time order: the alert frames of
the camera named like the output folder, then the clear images. Without
--alert only the clear images are written (a camera that never sees smoke).

    python scripts/make_scenario.py data/scenarios/<scenario>/croix-augas-01 \
        --alert data/replay_alerts/alert_49767.zip --preset 3 --frames 5

--preset writes the frames of one PTZ preset into <camera>/<preset>/ (the key of
`poses` in scenario.json, the `patrol_id` of the pose in the alert) and takes the
sequence seen on that pose. Presets without a folder play the frames of the camera
folder.
The scenario.json next to the camera folders is written by hand.
"""

import argparse
import json
import zipfile
from pathlib import Path


def alert_frames(alert_zip, camera_name, count, preset=None):
    zf = zipfile.ZipFile(alert_zip)
    alert = json.loads(zf.read("alert.json"))
    camera_id = next(
        k for k, cam in alert["cameras"].items() if cam["name"] == camera_name
    )
    sequences = [s for s in alert["sequences"] if str(s["camera_id"]) == camera_id]
    if preset is not None:
        poses = alert["cameras"][camera_id]["poses"]
        pose_ids = {p["id"] for p in poses if str(p["patrol_id"]) == preset}
        sequences = [s for s in sequences if s["pose_id"] in pose_ids]
        if not sequences:
            raise SystemExit(f"no sequence of {camera_name} on preset {preset}")
    sequence = sequences[0]
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
        "--preset",
        help="PTZ preset (patrol_id): write <camera>/<preset>/, that pose's sequence",
    )
    parser.add_argument(
        "--clear",
        type=Path,
        nargs="*",
        default=[],
        help="clear images appended at the end",
    )
    args = parser.parse_args()

    frames = (
        alert_frames(args.alert, args.out.name, args.frames, args.preset)
        if args.alert
        else []
    )
    frames += [path.read_bytes() for path in args.clear]
    out = args.out / args.preset if args.preset is not None else args.out
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.jpg"):
        stale.unlink()
    for i, data in enumerate(frames):
        (out / f"{i:03d}.jpg").write_bytes(data)
    print(f"{len(frames)} frames written to {out}")


if __name__ == "__main__":
    main()
