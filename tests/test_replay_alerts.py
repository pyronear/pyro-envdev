import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from replay_alerts import (  # noqa: E402
    build_rounds,
    day_offset,
    fmt_bboxes,
    parse_bboxes,
)


def det(ts, image, bbox, others=None):
    return {"recorded_at": ts, "image": image, "bbox": bbox, "others_bboxes": others}


def test_bboxes_drop_degenerate_and_format():
    boxes = parse_bboxes("[(0,0,0,0,0),(0.1,0.2,1.0,0.9999,0.5)]")
    assert fmt_bboxes(boxes) == "[(0.1,0.2,1,1,0.5)]"
    assert fmt_bboxes(parse_bboxes("[]")) == "[]"


def test_build_rounds_merges_shared_images_and_interleaves_cameras():
    alert = {
        "sequences": [
            {
                "camera_id": 1,
                "camera_azimuth": 10.0,
                "detections": [
                    det("2026-01-01T10:00:00", "a1", "[(0.1,0.1,0.2,0.2,0.5)]"),
                    det("2026-01-01T10:00:30", "a2", "[(0.1,0.1,0.2,0.2,0.6)]"),
                    det("2026-01-01T10:01:00", "a3", "[(0.1,0.1,0.2,0.2,0.7)]"),
                ],
            },
            {
                # second smoke on the same upload as a2: one frame, both boxes
                "camera_id": 1,
                "camera_azimuth": 10.0,
                "detections": [
                    det(
                        "2026-01-01T10:00:30",
                        "a2",
                        "[(0.5,0.5,0.6,0.6,0.4)]",
                        "[(0.1,0.1,0.2,0.2,0.6)]",
                    ),
                ],
            },
            {
                "camera_id": 2,
                "camera_azimuth": 200.0,
                "detections": [det("2026-01-01T10:00:10", "b1", "[]")],
            },
        ]
    }
    rounds = build_rounds(alert)
    assert [[f["image"] for f in r] for r in rounds] == [["a1", "b1"], ["a2"], ["a3"]]
    assert len(rounds[1][0]["boxes"]) == 2
    assert rounds[0][1]["boxes"] == []


def test_day_offset():
    alert = {
        "sequences": [
            {
                "camera_id": 1,
                "camera_azimuth": 0.0,
                "detections": [det("2026-01-01T23:59:00", "a", "[]")],
            }
        ]
    }
    rounds = build_rounds(alert)
    assert day_offset(rounds, "original") == timedelta(0)
    assert day_offset(rounds, "today") == date.today() - date(2026, 1, 1)
