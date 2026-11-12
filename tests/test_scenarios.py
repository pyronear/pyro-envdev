from __future__ import annotations

import json

import pytest

from tests.scenario import (
    NOT_CHECKED,
    SCENARIOS_DIR,
    ExpectedLocation,
    ScenarioError,
    haversine_km,
    load_scenario,
)

NAMES = sorted(p.parent.name for p in SCENARIOS_DIR.glob("*/scenario.json"))
CAMERAS = {"cam-a": {"poses": {"1": 10.0, "2": 20.0}}}


def write(tmp_path, expected, name="s"):
    (tmp_path / name).mkdir()
    doc = {"description": "d", "cameras": CAMERAS}
    if expected is not None:
        doc["expected"] = expected
    (tmp_path / name / "scenario.json").write_text(json.dumps(doc))
    return load_scenario(name, root=tmp_path)


def test_there_are_scenarios():
    assert {"smoke-then-clear", "never-smoke"} <= set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_every_shipped_scenario_loads(name):
    assert load_scenario(name).cameras


def test_smoke_then_clear_expected():
    expected = load_scenario("smoke-then-clear").expected
    assert expected.alerts == 5 and expected.timeout_s == 2400
    assert len(expected.sequences) == 7
    assert expected.location is NOT_CHECKED


def test_never_smoke_expected():
    expected = load_scenario("never-smoke").expected
    assert (expected.alerts, expected.sequences) == (0, [])


def test_no_expected_block_is_allowed(tmp_path):
    assert write(tmp_path, None).expected is None


def test_location_semantics(tmp_path):
    base = {"alerts": 1, "timeout_s": 10}
    assert write(tmp_path, base, "a").expected.location is NOT_CHECKED
    assert write(tmp_path, {**base, "location": None}, "b").expected.location is None
    loc = write(
        tmp_path, {**base, "location": {"lat": 1, "lon": 2, "tolerance_km": 3}}, "c"
    ).expected.location
    assert loc == ExpectedLocation(1, 2, 3)


def test_empty_or_absent_sequences_mean_not_checked(tmp_path):
    assert write(tmp_path, {"alerts": 0, "timeout_s": 10}, "a").expected.sequences == []
    assert (
        write(
            tmp_path, {"alerts": 0, "timeout_s": 10, "sequences": []}, "b"
        ).expected.sequences
        == []
    )


@pytest.mark.parametrize(
    "expected, message",
    [
        ({"alerts": 1, "timeout_s": 10, "typo": 1}, "unknown key"),
        ({"timeout_s": 10}, "alerts is required"),
        ({"alerts": 1}, "timeout_s is required"),
        (
            {
                "alerts": 1,
                "timeout_s": 10,
                "sequences": [{"camera": "nope", "preset": "1", "min_detections": 1}],
            },
            "unknown camera",
        ),
        (
            {
                "alerts": 1,
                "timeout_s": 10,
                "sequences": [{"camera": "cam-a", "preset": "9", "min_detections": 1}],
            },
            "no preset",
        ),
        (
            {
                "alerts": 1,
                "timeout_s": 10,
                "sequences": [
                    {"camera": "cam-a", "preset": "1", "min_detections": 1, "x": 1}
                ],
            },
            "unknown key",
        ),
        (
            {
                "alerts": 1,
                "timeout_s": 10,
                "sequences": [{"camera": "cam-a", "preset": "1"}],
            },
            "misses",
        ),
        ({"alerts": 1, "timeout_s": 10, "location": {"lat": 1, "lon": 2}}, "misses"),
        (
            {
                "alerts": 1,
                "timeout_s": 10,
                "location": {"lat": 1, "lon": 2, "tolerance_km": 3, "z": 4},
            },
            "unknown key",
        ),
        ({"alerts": "1", "timeout_s": 10}, "must be a number"),
    ],
)
def test_loader_rejects(tmp_path, expected, message):
    with pytest.raises(ScenarioError, match=message):
        write(tmp_path, expected)


def test_unknown_scenario(tmp_path):
    with pytest.raises(ScenarioError, match="no scenario"):
        load_scenario("nope", root=tmp_path)


def test_haversine():
    assert haversine_km(48.0, 2.0, 48.0, 2.0) == 0
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.19, abs=0.1)
