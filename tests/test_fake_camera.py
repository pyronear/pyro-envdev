import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "containers" / "fake_camera")
)
from server import frame_index  # noqa: E402

load_dotenv()

# fakecam-1 (croix-augas-01), published on the host by docker-compose.yml
BASE_URL = "https://127.0.0.1:8443"
AUTH = f"user={os.getenv('CAM_USER')}&password={os.getenv('CAM_PWD')}&channel=0"
# The fake camera uses a self-signed certificate, like pyro_camera_api (verify=False).
CTX = ssl._create_unverified_context()


def call(cmd, param=None, auth=AUTH):
    data = (
        None
        if param is None
        else json.dumps([{"cmd": cmd, "action": 0, "param": param}]).encode()
    )
    url = f"{BASE_URL}/cgi-bin/api.cgi?cmd={cmd}&{auth}"
    with urllib.request.urlopen(url, data=data, context=CTX, timeout=5) as resp:
        body = resp.read()
        return (
            body if resp.headers["Content-Type"] == "image/jpeg" else json.loads(body)
        )


def test_frame_index():
    assert frame_index(0, 30, 3) == 0
    assert frame_index(59.9, 30, 3) == 1
    assert frame_index(600, 30, 3) == 2  # last frame held


def test_snap_returns_a_jpeg():
    assert call("Snap")[:2] == b"\xff\xd8"


def test_wrong_password_is_rejected():
    assert call("Snap", auth="user=nobody&password=wrong&channel=0")[0]["code"] == 1


def test_ptz_follows_presets():
    assert (
        call("PtzCtrl", {"channel": 0, "op": "ToPos", "id": 3, "speed": 50})[0]["code"]
        == 0
    )
    with urllib.request.urlopen(f"{BASE_URL}/scenario", context=CTX, timeout=5) as resp:
        status = json.load(resp)
    assert status["preset"] == 3
    assert status["azimuth"] == 59.8
    # Preset 42 is not set on this camera
    assert (
        call("PtzCtrl", {"channel": 0, "op": "ToPos", "id": 42, "speed": 50})[0]["code"]
        == 1
    )
    presets = call("GetPtzPreset", {"channel": 0})[0]["value"]["PtzPreset"]
    assert [p["id"] for p in presets if p["enable"]] == [1, 2, 3]


def test_zoom_focus_values():
    zoom_focus = call("GetZoomFocus", {"channel": 0})[0]["value"]["ZoomFocus"]
    assert zoom_focus["focus"]["pos"] == 720
    assert zoom_focus["zoom"]["pos"] == 0
