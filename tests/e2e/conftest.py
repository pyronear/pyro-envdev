# ruff: noqa: E501
"""Fixtures for the end-to-end tests. They assume the stack is already up (make e2e) and never touch the network at import or collection time."""

from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from tests.e2e.helpers import wait_until
from tests.scenario import SCENARIOS_DIR, ScenarioError, load_scenario

ROOT = Path(__file__).resolve().parents[2]
API_URL = os.environ.get("E2E_API_URL", "http://localhost:5050").rstrip("/")
FAKECAM_URLS = [
    u.strip().rstrip("/")
    for u in os.environ.get(
        "E2E_FAKECAM_URLS", "https://127.0.0.1:8443,https://127.0.0.1:8444"
    ).split(",")
    if u.strip()
]
# Measured 2026-11-12 on emulated arm64 (e2e-step0-measurements): cameras first polled ~105 s after `up` started, first alert visible after 227 s.
ENGINE_START_TIMEOUT = float(os.environ.get("E2E_ENGINE_START_TIMEOUT", 300))
FIRST_ALERT_TIMEOUT = float(os.environ.get("E2E_FIRST_ALERT_TIMEOUT", 600))
# Measured settle after the cameras finish: 0 s.
SETTLE_WINDOW = float(os.environ.get("E2E_SETTLE_WINDOW", 60))
POLL_INTERVAL = float(os.environ.get("E2E_POLL_INTERVAL", 5))
TIMEOUT_MARGIN = 300

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
SESSION_START = datetime.now(timezone.utc)


def _scenario_name():
    return os.environ.get("SCENARIO")


def pytest_collection_modifyitems(config, items):
    name = _scenario_name()
    timeout = None
    try:
        expected = load_scenario(name).expected if name else None
        if expected:
            # The session fixtures wait up to first-alert + timeout_s + settle before the first test body runs, and that wait counts against the test that requests them.
            timeout = (
                expected.timeout_s
                + FIRST_ALERT_TIMEOUT
                + SETTLE_WINDOW
                + TIMEOUT_MARGIN
            )
    except (ScenarioError, OSError, ValueError):
        pass  # the `scenario` fixture reports the problem with a clear message
    for item in items:
        if "tests/e2e/" not in item.nodeid.replace(
            os.sep, "/"
        ) and "tests/e2e" not in str(item.fspath):
            continue
        item.add_marker(pytest.mark.e2e)
        if timeout and item.get_closest_marker("timeout") is None:
            item.add_marker(pytest.mark.timeout(timeout))


def camera_states():
    """GET /scenario of every fake camera, an {"error": ...} entry for one that does not answer."""
    states = []
    for url in FAKECAM_URLS:
        try:
            r = requests.get(f"{url}/scenario", verify=False, timeout=10)
            r.raise_for_status()
            states.append({"url": url, **r.json()})
        except (requests.RequestException, ValueError) as exc:
            states.append({"url": url, "error": repr(exc)})
    return states


def _alert_count(api):
    r = api.get(f"{API_URL}/api/v1/alerts/unlabeled/latest", timeout=30)
    r.raise_for_status()
    return len(r.json())


@pytest.fixture(scope="session")
def scenario():
    name = _scenario_name()
    if not name:
        pytest.fail(
            "SCENARIO is not set: run `make e2e SCENARIO=<name>` or export SCENARIO=<name> (see data/scenarios/)",
            pytrace=False,
        )
    try:
        loaded = load_scenario(name)
    except ScenarioError as exc:
        pytest.fail(str(exc), pytrace=False)
    if loaded.expected is None:
        pytest.fail(
            f"scenario {name!r} has no `expected` block in {SCENARIOS_DIR / name / 'scenario.json'}",
            pytrace=False,
        )
    for state in camera_states():
        if "error" in state:
            pytest.fail(
                f"fake camera {state['url']} does not answer GET /scenario: {state['error']}. Is the stack up?",
                pytrace=False,
            )
        if "scenario" not in state:
            pytest.fail(
                f"fake camera {state['url']} does not report a `scenario`: its image is older than this branch, rebuild it (make build-e2e)",
                pytrace=False,
            )
        if state["scenario"] != name:
            pytest.fail(
                f"fake camera {state['url']} plays {state['scenario']!r} but SCENARIO={name!r}",
                pytrace=False,
            )
    return loaded


def _new_session():
    session = requests.Session()
    # uvicorn closes idle connections after 5 s, the same as the poll interval, so a reused connection can be dropped mid-request: retry GETs.
    retry = Retry(total=3, backoff_factor=0.5, allowed_methods=["GET"])
    for prefix in ("http://", "https://"):
        session.mount(prefix, HTTPAdapter(max_retries=retry))
    return session


@pytest.fixture(scope="session")
def api():
    user, password = os.environ.get("E2E_USER"), os.environ.get("E2E_PASSWORD")
    if not user:
        with open(ROOT / "data" / "csv" / "API_DATA_DEV - users.csv") as f:
            row = next(r for r in csv.DictReader(f) if r["login"] == "test77")
        user, password = row["login"], row["password"]
    session = _new_session()
    r = session.post(
        f"{API_URL}/api/v1/login/creds",
        data={"username": user, "password": password},
        timeout=30,
    )
    assert (
        r.status_code == 200
    ), f"login as {user!r} on {API_URL} failed: {r.status_code} {r.text}"
    session.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return session


@pytest.fixture(scope="session")
def diagnose(api):
    def _diagnose():
        lines = [f"  {s}" for s in camera_states()]
        try:
            lines.append(f"  unlabeled alerts visible: {_alert_count(api)}")
        except requests.RequestException as exc:
            lines.append(f"  alert count unavailable: {exc!r}")
        return "state of the stack:\n" + "\n".join(lines)

    return _diagnose


@pytest.fixture(scope="session")
def first_alert(scenario, api, diagnose):
    def engine_never_polled(elapsed):
        states = camera_states() if elapsed >= ENGINE_START_TIMEOUT else []
        # a camera that does not answer (no "presets") is not proof of anything
        if (
            states
            and all("presets" in s for s in states)
            and not any(p["visits"] > 0 for s in states for p in s["presets"].values())
        ):
            return f"pyro_camera_api never polled the fake cameras (no preset visited after {ENGINE_START_TIMEOUT:.0f} s)"

    def latest():
        r = api.get(f"{API_URL}/api/v1/alerts/unlabeled/latest", timeout=30)
        r.raise_for_status()
        return r.json()

    return wait_until(
        latest,
        FIRST_ALERT_TIMEOUT,
        POLL_INTERVAL,
        "the first alert in /alerts/unlabeled/latest",
        diagnose,
        abort=engine_never_polled,
    )


def _all_alerts(api):
    # /alerts/all/fromdate matches one exact day, so query the day the session started and today (they differ if the run crosses UTC midnight).
    days = {
        SESSION_START.date().isoformat(),
        datetime.now(timezone.utc).date().isoformat(),
    }
    alerts = {}
    for day in sorted(days):
        offset = 0
        while True:
            r = api.get(
                f"{API_URL}/api/v1/alerts/all/fromdate",
                params={"from_date": day, "limit": 100, "offset": offset},
                timeout=60,
            )
            r.raise_for_status()
            page = r.json()
            alerts.update({a["id"]: a for a in page})
            if len(page) < 100:
                break
            offset += 100
    return list(alerts.values())


@pytest.fixture(scope="session")
def settled_alerts(scenario, api, diagnose):
    def finished():
        states = camera_states()
        return bool(states) and all(s.get("finished") is True for s in states)

    wait_until(
        finished,
        scenario.expected.timeout_s,
        POLL_INTERVAL,
        f"every fake camera to report finished (scenario {scenario.name})",
        diagnose,
    )
    time.sleep(SETTLE_WINDOW)
    return _all_alerts(api)
