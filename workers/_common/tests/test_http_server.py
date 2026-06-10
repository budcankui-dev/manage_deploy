from __future__ import annotations

import socket
import sys
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

COMMON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMMON_DIR))

from http_server import start_server  # noqa: E402


class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/ping":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"pong")

    def log_message(self, format, *args):
        pass


def _require_ipv6_loopback() -> int:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            sock.bind(("::1", 0))
            return sock.getsockname()[1]
    except OSError as exc:
        pytest.skip(f"IPv6 loopback is not available: {exc}")


def _eventually_get(host: str, port: int) -> str:
    deadline = time.time() + 3
    last_error: Exception | None = None
    while time.time() < deadline:
        conn: HTTPConnection | None = None
        try:
            conn = HTTPConnection(host, port, timeout=1)
            conn.request("GET", "/ping")
            resp = conn.getresponse()
            body = resp.read().decode()
            if resp.status == 200:
                return body
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)
        finally:
            if conn is not None:
                conn.close()
    raise AssertionError(f"GET http://{host}:{port}/ping failed: {last_error}")


def test_start_server_accepts_ipv6_and_ipv4_loopback():
    port = _require_ipv6_loopback()

    start_server(port, PingHandler)

    assert _eventually_get("::1", port) == "pong"
    assert _eventually_get("127.0.0.1", port) == "pong"
