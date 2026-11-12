# ruff: noqa: E501
"""Loader for data/scenarios/<name>/scenario.json, including the optional `expected` block."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "data" / "scenarios"
EXPECTED_KEYS = {"alerts", "sequences", "location", "timeout_s"}
SEQUENCE_KEYS = {"camera", "preset", "min_detections"}
LOCATION_KEYS = {"lat", "lon", "tolerance_km"}
# Distinguishes "location key absent" (not checked) from `"location": null` (all alerts have no position).
NOT_CHECKED = "not_checked"


class ScenarioError(ValueError):
    pass


@dataclass
class ExpectedSequence:
    camera: str
    preset: str
    min_detections: int


@dataclass
class ExpectedLocation:
    lat: float
    lon: float
    tolerance_km: float


@dataclass
class Expected:
    alerts: int
    timeout_s: int
    sequences: List[ExpectedSequence] = field(default_factory=list)
    # NOT_CHECKED, None (every alert has null lat/lon) or an ExpectedLocation
    location: object = NOT_CHECKED


@dataclass
class Scenario:
    name: str
    description: str
    cameras: Dict[str, Dict[str, float]]
    expected: Optional[Expected]


def _unknown(where: str, got: dict, allowed: set) -> None:
    extra = sorted(set(got) - allowed)
    if extra:
        raise ScenarioError(
            f"unknown key(s) in {where}: {extra}, allowed: {sorted(allowed)}"
        )


def _require_number(where: str, value, kind=(int, float)) -> None:
    if isinstance(value, bool) or not isinstance(value, kind):
        raise ScenarioError(f"{where} must be a number, got {value!r}")


def _parse_expected(name: str, raw: dict, cameras: dict) -> Expected:
    where = f"{name}: expected"
    if not isinstance(raw, dict):
        raise ScenarioError(f"{where} must be an object")
    _unknown(where, raw, EXPECTED_KEYS)
    for key in ("alerts", "timeout_s"):
        if key not in raw:
            raise ScenarioError(f"{where}.{key} is required")
        _require_number(f"{where}.{key}", raw[key], int)
    sequences = []
    for i, seq in enumerate(raw.get("sequences") or []):
        _unknown(f"{where}.sequences[{i}]", seq, SEQUENCE_KEYS)
        missing = SEQUENCE_KEYS - set(seq)
        if missing:
            raise ScenarioError(f"{where}.sequences[{i}] misses {sorted(missing)}")
        camera, preset = seq["camera"], str(seq["preset"])
        if camera not in cameras:
            raise ScenarioError(
                f"{where}.sequences[{i}]: unknown camera {camera!r}, known: {sorted(cameras)}"
            )
        if preset not in cameras[camera]:
            raise ScenarioError(
                f"{where}.sequences[{i}]: camera {camera!r} has no preset {preset!r}, known: {sorted(cameras[camera])}"
            )
        _require_number(
            f"{where}.sequences[{i}].min_detections", seq["min_detections"], int
        )
        sequences.append(ExpectedSequence(camera, preset, seq["min_detections"]))
    location: object = NOT_CHECKED
    if "location" in raw:
        loc = raw["location"]
        if loc is None:
            location = None
        else:
            if not isinstance(loc, dict):
                raise ScenarioError(f"{where}.location must be null or an object")
            _unknown(f"{where}.location", loc, LOCATION_KEYS)
            missing = LOCATION_KEYS - set(loc)
            if missing:
                raise ScenarioError(f"{where}.location misses {sorted(missing)}")
            for key in LOCATION_KEYS:
                _require_number(f"{where}.location.{key}", loc[key])
            location = ExpectedLocation(loc["lat"], loc["lon"], loc["tolerance_km"])
    return Expected(raw["alerts"], raw["timeout_s"], sequences, location)


def load_scenario(name: str, root: Path = SCENARIOS_DIR) -> Scenario:
    path = Path(root) / name / "scenario.json"
    if not path.is_file():
        raise ScenarioError(f"no scenario {name!r}: {path} does not exist")
    raw = json.loads(path.read_text())
    cameras = {
        cam: {str(k): v for k, v in spec["poses"].items()}
        for cam, spec in raw["cameras"].items()
    }
    expected = (
        _parse_expected(name, raw["expected"], cameras) if "expected" in raw else None
    )
    return Scenario(name, raw.get("description", ""), cameras, expected)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(math.sqrt(a))
