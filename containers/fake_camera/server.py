"""Fake Reolink camera.

Answers the Reolink HTTP API (``/cgi-bin/api.cgi?cmd=...``) the way the real
``pyro_camera_api`` Reolink adapter expects, serving the frames of a scenario.
One process is one camera: ``SCENARIO`` and ``CAMERA`` select
``<SCENARIOS_DIR>/<SCENARIO>/<CAMERA>/*.jpg`` (sorted, last frame held).
Each preset moves to its next frame on its next visit: the first Snap after a
ToPos, so snaps taken in place (autofocus) see the same frame. A camera never
positioned (static) moves on every Snap.

``GET /scenario`` is not part of the Reolink API: it reports the camera state
(preset, azimuth, frame, finished) so tests know where the scenario is.
"""

import json
import logging
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# A Reolink PTZ camera exposes 64 preset slots, ids 0..63.
PRESET_SLOTS = 64
# PTZ operations that leave the current preset; Stop and zoom/focus do not pan.
NO_PAN_OPS = {"ToPos", "Stop", "ZoomInc", "ZoomDec", "FocusInc", "FocusDec"}

CAM_USER = os.environ.get("CAM_USER", "")
CAM_PWD = os.environ.get("CAM_PWD", "")
# Replay the scenario from the start once the last frame is reached.
LOOP = os.environ.get("LOOP", "false").lower() in ("1", "true", "yes")


def frame_index(visits, n_frames, loop=False):
    """Frame served on the `visits`-th visit of a preset (1 = first).

    The last frame is held, or the scenario starts again with `loop`.
    """
    index = max(0, visits - 1)
    return index % n_frames if loop else min(n_frames - 1, index)


def reply(cmd, value=None, error=None):
    if error:
        return [{"cmd": cmd, "code": 1, "error": {"detail": error, "rspCode": -9}}]
    return [
        {"cmd": cmd, "code": 0, "value": {"rspCode": 200} if value is None else value}
    ]


class Camera:
    def __init__(self, scenario_dir, name):
        meta = json.loads((scenario_dir / "scenario.json").read_text())
        self.name = name
        # preset id -> real-world azimuth, informational only (see /scenario)
        self.azimuths = {
            int(k): float(v) for k, v in meta["cameras"][name]["poses"].items()
        }
        # ponytail: every preset serves the same frames; per-preset folders if needed
        self.frames = sorted((scenario_dir / name).glob("*.jpg"))
        if not self.frames:
            raise SystemExit(
                f"no frames in {scenario_dir / name}, run `make fetch-scenario` first"
            )
        self.lock = threading.Lock()
        self.preset = None  # unknown until a ToPos; stays None on a static camera
        self.visits = {}  # preset -> visits that took a Snap
        self.arrived = True  # the next Snap is the first at the current position
        self.enabled = set(self.azimuths)
        self.zoom, self.focus, self.autofocus_disabled = 0, 720, 0

    def _frame(self, preset):
        return frame_index(self.visits.get(preset, 0), len(self.frames), LOOP)

    def snap(self):
        with self.lock:
            if self.arrived or self.preset is None:
                self.visits[self.preset] = self.visits.get(self.preset, 0) + 1
                self.arrived = False
            return self.frames[self._frame(self.preset)].read_bytes()

    def status(self):
        with self.lock:
            return {
                "camera": self.name,
                "preset": self.preset,
                "azimuth": self.azimuths.get(self.preset),
                "frame": self._frame(self.preset),
                "frames": len(self.frames),
                "loop": LOOP,
                "finished": not LOOP
                and bool(self.visits)
                and all(self._frame(p) == len(self.frames) - 1 for p in self.visits),
            }

    def command(self, cmd, param):
        with self.lock:
            if cmd == "PtzCtrl":
                op = param.get("op")
                if op == "ToPos":
                    idx = int(param.get("id", 0))
                    if idx not in self.enabled:
                        return reply(cmd, error=f"preset {idx} is not set")
                    self.preset = idx
                    self.arrived = True
                elif op not in NO_PAN_OPS:
                    self.preset = None
                return reply(cmd)
            if cmd == "GetPtzPreset":
                presets = [
                    {
                        "channel": 0,
                        "enable": int(i in self.enabled),
                        "id": i,
                        "name": f"pos{i}",
                    }
                    for i in range(PRESET_SLOTS)
                ]
                return reply(cmd, {"PtzPreset": presets})
            if cmd == "SetPtzPreset":
                preset = param.get("PtzPreset", {})
                idx = int(preset.get("id", 0))
                if preset.get("enable", 1):
                    self.enabled.add(idx)
                else:
                    self.enabled.discard(idx)
                return reply(cmd)
            if cmd == "GetZoomFocus":
                zoom_focus = {
                    "channel": 0,
                    "focus": {"pos": self.focus},
                    "zoom": {"pos": self.zoom},
                }
                return reply(cmd, {"ZoomFocus": zoom_focus})
            if cmd == "StartZoomFocus":
                zoom_focus = param.get("ZoomFocus", {})
                if zoom_focus.get("op") == "FocusPos":
                    self.focus = int(zoom_focus.get("pos", self.focus))
                else:
                    self.zoom = int(zoom_focus.get("pos", self.zoom))
                return reply(cmd)
            if cmd == "GetAutoFocus":
                return reply(
                    cmd,
                    {"AutoFocus": {"channel": 0, "disable": self.autofocus_disabled}},
                )
            if cmd == "SetAutoFocus":
                self.autofocus_disabled = int(
                    param.get("AutoFocus", {}).get("disable", 0)
                )
                return reply(cmd)
            if cmd == "Reboot":
                return reply(cmd)
            return reply(cmd, error=f"unsupported command {cmd}")


camera = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # The default logs the full URL, which carries the camera password.
        logging.info("%s %s", self.command, urlparse(self.path).path)

    def _send(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data):
        self._send(200, json.dumps(data).encode())

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def _dispatch(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/scenario":
            return self._json(camera.status())
        if url.path != "/cgi-bin/api.cgi":
            return self._send(404, b"not found", "text/plain")
        cmd = query.get("cmd", [""])[0]
        if (query.get("user", [""])[0], query.get("password", [""])[0]) != (
            CAM_USER,
            CAM_PWD,
        ):
            return self._json(
                [
                    {
                        "cmd": cmd,
                        "code": 1,
                        "error": {"detail": "please login first", "rspCode": -6},
                    }
                ]
            )
        if cmd == "Snap":
            return self._send(200, camera.snap(), "image/jpeg")
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"[]")
        param = body[0].get("param", {}) if body else {}
        return self._json(camera.command(cmd, param))


def main():
    global camera
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    scenario = os.environ["SCENARIO"]
    camera = Camera(
        Path(os.environ.get("SCENARIOS_DIR", "/scenarios")) / scenario,
        os.environ["CAMERA"],
    )
    port = int(os.environ.get("PORT", "443"))
    here = Path(__file__).parent
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        os.environ.get("CERT_FILE", here / "cert.pem"),
        os.environ.get("KEY_FILE", here / "key.pem"),
    )
    httpd = ThreadingHTTPServer(("", port), Handler)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    logging.info(
        "fake camera %s plays scenario %s%s: "
        "%d frames, one per preset visit, presets %s, port %d",
        camera.name,
        scenario,
        " in a loop" if LOOP else "",
        len(camera.frames),
        sorted(camera.enabled),
        port,
    )
    httpd.serve_forever()


if __name__ == "__main__":
    main()
