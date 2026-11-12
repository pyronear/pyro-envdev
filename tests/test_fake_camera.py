import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

import pytest
from dotenv import load_dotenv

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "containers" / "fake_camera")
)
from server import Camera, frame_index  # noqa: E402

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
    assert frame_index(0, 3) == 0  # never visited
    assert frame_index(1, 3) == 0  # first visit
    assert frame_index(2, 3) == 1
    assert frame_index(20, 3) == 2  # last frame held


def test_one_frame_per_preset_visit(tmp_path):
    (tmp_path / "scenario.json").write_text(
        json.dumps({"cameras": {"cam": {"poses": {"1": 0.0, "2": 90.0}}}})
    )
    (tmp_path / "cam").mkdir()
    for i in range(3):
        (tmp_path / "cam" / f"{i:03d}.jpg").write_bytes(b"frame%d" % i)
    cam = Camera(tmp_path, "cam")

    def visit(preset, snaps=1):
        cam.command("PtzCtrl", {"op": "ToPos", "id": preset})
        return [cam.snap() for _ in range(snaps)]

    assert visit(1, snaps=3) == [b"frame0"] * 3  # autofocus snaps in place: same frame
    assert visit(2) == [b"frame0"]  # each preset starts at the first frame
    assert visit(1) == [b"frame1"]
    assert visit(1) == [b"frame2"]
    assert visit(1) == [b"frame2"]  # last frame held
    assert not cam.status()["finished"]  # preset 2 is still on its first frame


def test_static_camera_moves_on_every_snap(tmp_path):
    (tmp_path / "scenario.json").write_text(
        json.dumps({"cameras": {"cam": {"poses": {}}}})
    )
    (tmp_path / "cam").mkdir()
    for i in range(2):
        (tmp_path / "cam" / f"{i:03d}.jpg").write_bytes(b"frame%d" % i)
    cam = Camera(tmp_path, "cam")
    assert [cam.snap() for _ in range(3)] == [b"frame0", b"frame1", b"frame1"]
    assert cam.status()["finished"]


def make_camera(tmp_path, poses, camera_frames=(), preset_frames=None):
    """A Camera over a scenario: poses, camera-level frames, frames per preset."""
    (tmp_path / "scenario.json").write_text(
        json.dumps({"cameras": {"cam": {"poses": poses}}})
    )
    (tmp_path / "cam").mkdir()
    for i, data in enumerate(camera_frames):
        (tmp_path / "cam" / f"{i:03d}.jpg").write_bytes(data)
    for preset, frames in (preset_frames or {}).items():
        (tmp_path / "cam" / preset).mkdir()
        for i, data in enumerate(frames):
            (tmp_path / "cam" / preset / f"{i:03d}.jpg").write_bytes(data)
    return Camera(tmp_path, "cam", "scn")


def visit(cam, preset):
    cam.command("PtzCtrl", {"op": "ToPos", "id": preset})
    return cam.snap()


def test_each_preset_plays_its_own_frames(tmp_path):
    cam = make_camera(
        tmp_path,
        {"1": 0.0, "2": 90.0, "3": 180.0},
        camera_frames=[b"shared"],
        preset_frames={"2": [b"smoke0", b"smoke1", b"smoke2"]},
    )
    assert visit(cam, 1) == b"shared"
    assert visit(cam, 3) == b"shared"
    assert visit(cam, 2) == b"smoke0"
    assert not cam.status()["finished"]
    assert visit(cam, 2) == b"smoke1"
    assert not cam.status()["finished"]  # the others are done, preset 2 is not
    assert visit(cam, 2) == b"smoke2"
    assert cam.status()["finished"]
    assert visit(cam, 2) == b"smoke2"  # last frame held
    status = cam.status()
    assert (status["preset"], status["frame"], status["frames"]) == (2, 2, 3)
    assert status["presets"] == {
        "1": {"visits": 1, "frame": 0, "frames": 1},
        "2": {"visits": 4, "frame": 2, "frames": 3},
        "3": {"visits": 1, "frame": 0, "frames": 1},
    }


def test_a_preset_never_visited_is_not_finished(tmp_path):
    cam = make_camera(tmp_path, {"1": 0.0, "2": 90.0}, camera_frames=[b"shared"])
    visit(cam, 1)
    assert not cam.status()["finished"]
    visit(cam, 2)
    assert cam.status()["finished"]


def test_camera_level_frames_only_behave_as_before(tmp_path):
    cam = make_camera(
        tmp_path,
        {"1": 0.0, "2": 90.0},
        camera_frames=[b"frame0", b"frame1", b"frame2"],
    )
    assert [visit(cam, 1) for _ in range(4)] == [b"frame0", b"frame1", b"frame2"] + [
        b"frame2"
    ]
    assert visit(cam, 2) == b"frame0"
    status = cam.status()
    assert (status["frame"], status["frames"], status["finished"]) == (0, 3, False)


def test_a_snap_before_any_to_pos_does_not_change_finished(tmp_path):
    cam = make_camera(tmp_path, {"1": 0.0}, camera_frames=[b"f0", b"f1"])
    cam.snap()
    cam.snap()
    assert not cam.status()["finished"]  # does not trigger
    visit(cam, 1)
    assert not cam.status()["finished"]
    visit(cam, 1)
    assert cam.status()["finished"]
    (tmp_path / "b").mkdir()
    other = make_camera(tmp_path / "b", {"1": 0.0}, camera_frames=[b"f0"])
    visit(other, 1)
    other.command("PtzCtrl", {"op": "Left"})  # leaves the preset
    other.snap()
    assert other.status()["finished"]  # does not block


def test_a_preset_without_frames_fails_at_start(tmp_path):
    with pytest.raises(SystemExit) as exc:
        make_camera(
            tmp_path, {"1": 0.0, "2": 90.0}, preset_frames={"1": [b"only preset 1"]}
        )
    message = str(exc.value)
    assert "scn" in message and "cam" in message and "preset 2" in message


def test_status_reports_the_scenario_name(tmp_path):
    (tmp_path / "scenario.json").write_text(
        json.dumps({"cameras": {"cam": {"poses": {"1": 0.0}}}})
    )
    (tmp_path / "cam").mkdir()
    (tmp_path / "cam" / "000.jpg").write_bytes(b"frame0")
    cam = Camera(tmp_path, "cam", "smoke-then-clear")
    assert cam.status()["scenario"] == "smoke-then-clear"
    assert Camera(tmp_path, "cam").status()["scenario"] is None


@pytest.mark.integration
def test_snap_returns_a_jpeg():
    assert call("Snap")[:2] == b"\xff\xd8"


@pytest.mark.integration
def test_wrong_password_is_rejected():
    assert call("Snap", auth="user=nobody&password=wrong&channel=0")[0]["code"] == 1


@pytest.mark.integration
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


@pytest.mark.integration
def test_zoom_focus_values():
    zoom_focus = call("GetZoomFocus", {"channel": 0})[0]["value"]["ZoomFocus"]
    assert zoom_focus["focus"]["pos"] == 720
    assert zoom_focus["zoom"]["pos"] == 0
