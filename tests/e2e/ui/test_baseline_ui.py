# ruff: noqa: E501
"""Read-only checks of what the platform shows for the alert. Nothing here acknowledges, labels or changes the alert."""
from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import API_URL
from tests.e2e.ui.conftest import (
    ALERT_CARD_PREFIX,
    HIDE_CROP_BUTTON,
    SHOW_CROP_BUTTON,
    UI_TIMEOUT_MS,
    open_alert,
)

# True when one <img> of the page has this path (no query string: a presigned URL carries a signature that changes between two requests) and has decoded pixels.
LOADED_IMAGE_WITH_PATH = """paths => [...document.images].some(
    img => img.complete && img.naturalWidth > 0 && paths.includes(new URL(img.src).pathname)
)"""


@pytest.fixture
def detection_paths(alert_sequence, api):
    """URL paths of the full images and of the crops the API serves for the sequence."""
    _, sequence = alert_sequence
    r = api.get(
        f"{API_URL}/api/v1/sequences/{sequence['id']}/detections",
        params={"with_crop": "true", "limit": 100},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    detections = r.json()
    assert detections, f"sequence {sequence['id']} has no detection"
    return (
        [urlsplit(d["url"]).path for d in detections],
        [urlsplit(d["crop_url"]).path for d in detections],
    )


def test_alert_card_shows_camera(alert_page, alert_sequence):
    camera_name, _ = alert_sequence
    card = open_alert(alert_page, camera_name)
    expect(card).to_contain_text(ALERT_CARD_PREFIX)
    expect(card).to_contain_text(camera_name)


def test_player_image_loaded(alert_page, alert_sequence, detection_paths):
    camera_name, _ = alert_sequence
    image_paths, _ = detection_paths
    open_alert(alert_page, camera_name)
    # The player plays on its own, so it can show any detection of the sequence.
    alert_page.wait_for_function(
        LOADED_IMAGE_WITH_PATH, arg=image_paths, timeout=UI_TIMEOUT_MS
    )


def test_crop_toggle(alert_page, alert_sequence, detection_paths):
    camera_name, _ = alert_sequence
    _, crop_paths = detection_paths
    open_alert(alert_page, camera_name)
    # The close-up is shown by default, and it is one of the crops the API serves for this sequence.
    alert_page.wait_for_function(
        LOADED_IMAGE_WITH_PATH, arg=crop_paths, timeout=UI_TIMEOUT_MS
    )
    alert_page.get_by_role("button", name=HIDE_CROP_BUTTON).click()
    alert_page.get_by_role("button", name=SHOW_CROP_BUTTON).wait_for()
    assert not alert_page.evaluate(
        "paths => [...document.images].some(img => paths.includes(new URL(img.src).pathname))",
        crop_paths,
    ), "a crop is still on the page after hiding the close-up"
    alert_page.get_by_role("button", name=SHOW_CROP_BUTTON).click()
    alert_page.wait_for_function(
        LOADED_IMAGE_WITH_PATH, arg=crop_paths, timeout=UI_TIMEOUT_MS
    )
