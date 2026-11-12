# ruff: noqa: E501
from __future__ import annotations

import json

import pytest
import requests

from tests.e2e.conftest import API_URL, ROOT
from tests.scenario import NOT_CHECKED, haversine_km

JPEG_MAGIC = b"\xff\xd8\xff"


def _pose_ids():
    """(camera name, preset) -> pose_id, from data/credentials.json where `poses` and `pose_ids` are matched positionally."""
    creds = json.loads((ROOT / "data" / "credentials.json").read_text())
    return {
        (c["name"], str(p)): pid
        for c in creds.values()
        for p, pid in zip(c["poses"], c["pose_ids"])
    }


def _sequences(alerts):
    return [s for a in alerts for s in a["sequences"]]


def _require_alerts(scenario):
    if scenario.expected.alerts == 0:
        pytest.skip("scenario expects no alert")


def test_first_alert_appears(scenario, request):
    _require_alerts(scenario)
    assert request.getfixturevalue("first_alert")


def test_alert_count(scenario, settled_alerts):
    assert len(settled_alerts) == scenario.expected.alerts, [
        a["id"] for a in settled_alerts
    ]


def test_expected_sequences(scenario, settled_alerts, api):
    if not scenario.expected.sequences:
        pytest.skip("scenario lists no sequence to check")
    cameras = {
        c["name"]: c["id"]
        for c in api.get(f"{API_URL}/api/v1/cameras/", timeout=30).json()
    }
    pose_ids = _pose_ids()
    by_key = {(s["camera_id"], s["pose_id"]): s for s in _sequences(settled_alerts)}
    problems = []
    for exp in scenario.expected.sequences:
        key = (cameras.get(exp.camera), pose_ids.get((exp.camera, exp.preset)))
        seq = by_key.get(key)
        if seq is None:
            problems.append(
                f"{exp.camera} preset {exp.preset} (camera_id, pose_id)={key}: no sequence"
            )
        elif seq["detections_count"] < exp.min_detections:
            problems.append(
                f"{exp.camera} preset {exp.preset}: {seq['detections_count']} detections, expected at least {exp.min_detections}"
            )
    assert not problems, "\n".join(problems)


def _fetch_image(url):
    r = requests.get(url, timeout=60)
    assert r.status_code == 200, f"{r.status_code} for {url}"
    assert r.content[:3] == JPEG_MAGIC, f"not a JPEG: {url}"


def test_detections_have_images(scenario, settled_alerts, api):
    _require_alerts(scenario)
    sequences = _sequences(settled_alerts)
    assert sequences, "alerts carry no sequence"
    for seq in sequences:
        r = api.get(
            f"{API_URL}/api/v1/sequences/{seq['id']}/detections",
            params={"with_crop": "true", "limit": 100},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        detections = r.json()
        assert detections, f"sequence {seq['id']} has no detection"
        for d in detections:
            assert d.get(
                "url"
            ), f"sequence {seq['id']} detection {d.get('id')}: empty url"
            assert d.get(
                "crop_url"
            ), f"sequence {seq['id']} detection {d.get('id')}: empty crop_url"
        for d in (detections[0], detections[len(detections) // 2], detections[-1]):
            _fetch_image(d["url"])
            _fetch_image(d["crop_url"])


def test_location(scenario, settled_alerts):
    expected = scenario.expected.location
    if expected is NOT_CHECKED:
        pytest.skip("scenario does not check the location")
    if expected is None:
        located = [
            a["id"]
            for a in settled_alerts
            if a.get("lat") is not None or a.get("lon") is not None
        ]
        assert not located, f"alerts with a position: {located}"
        return
    distances = {
        a["id"]: haversine_km(expected.lat, expected.lon, a["lat"], a["lon"])
        for a in settled_alerts
        if a.get("lat") is not None and a.get("lon") is not None
    }
    assert (
        distances and min(distances.values()) <= expected.tolerance_km
    ), f"distance in km to ({expected.lat}, {expected.lon}) per alert: {distances}"
