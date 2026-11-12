# ruff: noqa: E501
from __future__ import annotations

import http.server
import threading

import pytest

from tests.e2e.conftest import _new_session
from tests.e2e.helpers import WaitError, wait_until


def test_wait_until_returns_first_truthy_value():
    values = iter([None, 0, "ready"])
    assert wait_until(lambda: next(values), 5, 0.01, "a value") == "ready"


def test_wait_until_timeout_message_names_what_elapsed_last_value_and_diagnosis():
    with pytest.raises(WaitError) as exc:
        wait_until(
            lambda: [],
            0.2,
            0.05,
            "the first alert",
            diagnose=lambda: "cameras: frame 0",
        )
    msg = str(exc.value)
    assert "the first alert" in msg
    assert "elapsed 0 s of 0 s" in msg
    assert "last value: []" in msg
    assert "cameras: frame 0" in msg


def test_wait_until_aborts_early_with_the_reason():
    with pytest.raises(WaitError) as exc:
        wait_until(
            lambda: None,
            60,
            0.01,
            "an alert",
            abort=lambda elapsed: "pyro_camera_api never polled the fake cameras (no camera left frame 0 after 300 s)",
        )
    msg = str(exc.value)
    assert msg.startswith(
        "pyro_camera_api never polled the fake cameras (no camera left frame 0 after 300 s)"
    )
    assert "awaited: an alert" in msg


def test_session_get_survives_a_dropped_connection():
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            seen.append(1)
            if len(seen) == 1:
                self.close_connection = (
                    True  # nothing written: the client sees RemoteDisconnected
                )
                return
            body = b"[]"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with _new_session() as session:  # closing it frees the keep-alive handler thread
            r = session.get(f"http://127.0.0.1:{server.server_port}/", timeout=5)
        assert r.status_code == 200 and len(seen) >= 2
    finally:
        server.shutdown()
        server.server_close()
