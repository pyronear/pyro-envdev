# ruff: noqa: E501
"""Fixtures for the browser tests: one login for the whole session, a pinned locale, and an alert page opened after the alert exists."""

from __future__ import annotations

import os
import re

import pytest

from tests.e2e.conftest import API_URL, e2e_credentials

PLATFORM_URL = os.environ.get("E2E_PLATFORM_URL", "http://localhost:8080").rstrip("/")
# The platform picks its language from navigator.language (i18next-browser-languagedetector, supported: en, fr, es, de), so a pinned en-US makes the strings below stable.
LOCALE = "en-US"
TIMEZONE = "UTC"
# A generous wait for the first paint of a page and for images served through the presigned URLs.
UI_TIMEOUT_MS = 30_000

# UI strings, from src/locales/en/translation.json of new-pyro-platform.
LOGIN_USERNAME_LABEL = re.compile(r"^Username")
LOGIN_PASSWORD_LABEL = re.compile(r"^Password")
LOGIN_BUTTON = "Login"
ALERT_CARD_PREFIX = "Detected by :"
HIDE_CROP_BUTTON = "Hide close-up"
SHOW_CROP_BUTTON = "Show close-up"
AUTH_TOKEN_KEY = "auth_token"


@pytest.fixture(scope="session")
def base_url():
    return PLATFORM_URL


@pytest.fixture(scope="session")
def e2e_storage_state(browser, tmp_path_factory):
    """Log in once through the real login page and return the path of the saved storage state (the token lives in localStorage)."""
    user, password = e2e_credentials()
    context = browser.new_context(
        base_url=PLATFORM_URL, locale=LOCALE, timezone_id=TIMEZONE
    )
    try:
        page = context.new_page()
        page.goto("/login")
        page.get_by_label(LOGIN_USERNAME_LABEL).fill(user)
        page.get_by_label(LOGIN_PASSWORD_LABEL).fill(password)
        page.get_by_role("button", name=LOGIN_BUTTON).click()
        page.wait_for_function(
            "key => localStorage.getItem(key) !== null",
            arg=AUTH_TOKEN_KEY,
            timeout=UI_TIMEOUT_MS,
        )
        path = tmp_path_factory.mktemp("ui-auth") / "storage_state.json"
        context.storage_state(path=str(path))
    finally:
        context.close()
    return str(path)


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, e2e_storage_state):
    return {
        **browser_context_args,
        "storage_state": e2e_storage_state,
        "locale": LOCALE,
        "timezone_id": TIMEZONE,
    }


def open_alert(page, camera_name):
    """Open the alerts view and select the alert card of this camera, return the card."""
    page.goto("/alerts")
    card = page.get_by_role("button").filter(has_text=camera_name)
    card.first.wait_for(timeout=UI_TIMEOUT_MS)
    card.first.click()
    return card.first


@pytest.fixture
def alert_page(first_alert, page):
    """A page with the UI timeout set, created only once the alert exists in the API (the platform only refreshes its list every 30 s)."""
    page.set_default_timeout(UI_TIMEOUT_MS)
    return page


@pytest.fixture(scope="session")
def alert_sequence(scenario, first_alert, api):
    """(camera name, sequence dict) of the first sequence the scenario expects, as the API serves it."""
    if not scenario.expected.sequences:
        pytest.skip("scenario lists no sequence to look at")
    camera_name = scenario.expected.sequences[0].camera
    cameras = api.get(f"{API_URL}/api/v1/cameras/", timeout=30).json()
    camera_id = next(c["id"] for c in cameras if c["name"] == camera_name)
    sequences = [s for a in first_alert for s in a["sequences"]]
    sequence = next((s for s in sequences if s["camera_id"] == camera_id), None)
    assert sequence, f"no sequence of {camera_name} in the first alert"
    return camera_name, sequence
