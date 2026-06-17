from __future__ import annotations

import json
import socket
import sys
import time
from http.client import HTTPConnection
from pathlib import Path

WORKERS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKERS_DIR))

from _common.http_server import start_server  # noqa: E402
from _common.receiver_server import ReceiverHandler, ReceiverStore  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request_json(method: str, port: int, path: str, body: dict | None = None) -> tuple[int, dict]:
    deadline = time.time() + 3
    last_error: Exception | None = None
    while time.time() < deadline:
        conn: HTTPConnection | None = None
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=1)
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
            headers = {"Content-Type": "application/json"} if payload is not None else {}
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            data = json.loads(response.read().decode("utf-8"))
            return response.status, data
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)
        finally:
            if conn is not None:
                conn.close()
    raise AssertionError(f"{method} {path} failed: {last_error}")


def _request_text(method: str, port: int, path: str) -> tuple[int, str, str]:
    conn = HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request(method, path)
        response = conn.getresponse()
        return response.status, response.getheader("Content-Type", ""), response.read().decode("utf-8")
    finally:
        conn.close()


def test_receiver_accepts_callback_and_serves_order_result(tmp_path):
    port = _free_port()
    ReceiverHandler.task_type = "high_throughput_matmul"
    ReceiverHandler.store = ReceiverStore(tmp_path)
    start_server(port, ReceiverHandler)

    payload = {
        "order_id": "order-123",
        "task_type": "high_throughput_matmul",
        "result": {"effective_gflops": 123.4},
    }
    status, posted = _request_json("POST", port, "/callback", payload)
    assert status == 200
    assert posted["status"] == "ok"
    assert posted["order_id"] == "order-123"
    assert posted["payload"]["result"]["effective_gflops"] == 123.4

    status, latest = _request_json("GET", port, "/latest")
    assert status == 200
    assert latest["latest"]["order_id"] == "order-123"

    status, fetched = _request_json("GET", port, "/orders/order-123")
    assert status == 200
    assert fetched["task_type"] == "high_throughput_matmul"
    assert fetched["payload"] == payload
    assert (tmp_path / "order-123.json").exists()


def test_receiver_homepage_renders_latest_result_for_demo(tmp_path):
    port = _free_port()
    ReceiverHandler.task_type = "low_latency_video_pipeline"
    ReceiverHandler.store = ReceiverStore(tmp_path)
    start_server(port, ReceiverHandler)

    _request_json(
        "POST",
        port,
        "/callback",
        {
            "order_id": "video-order-1",
            "metric_key": "frame_latency_p90_ms",
            "result": {
                "frame_latency_p90_ms": 18.6,
                "top_label_zh": "车辆",
                "annotated_frame_data_url": "data:image/jpeg;base64,abc123",
            },
        },
    )

    status, content_type, body = _request_text("GET", port, "/")
    assert status == 200
    assert "text/html" in content_type
    assert "用户端结果接收器" in body
    assert "video-order-1" in body
    assert "frame_latency_p90_ms: 18.6" in body
    assert "车辆" in body
    assert '<img class="preview" src="data:image/jpeg;base64,abc123"' in body


def test_receiver_homepage_rejects_svg_data_url_preview(tmp_path):
    port = _free_port()
    ReceiverHandler.task_type = "low_latency_video_pipeline"
    ReceiverHandler.store = ReceiverStore(tmp_path)
    start_server(port, ReceiverHandler)

    _request_json(
        "POST",
        port,
        "/callback",
        {
            "order_id": "video-order-svg",
            "metric_key": "frame_latency_p90_ms",
            "result": {
                "frame_latency_p90_ms": 18.6,
                "annotated_frame_data_url": "data:image/svg+xml;base64,PHN2Zy8+",
            },
        },
    )

    status, content_type, body = _request_text("GET", port, "/")
    assert status == 200
    assert "text/html" in content_type
    assert '<img class="preview"' not in body


def test_receiver_fetching_old_order_does_not_change_latest(tmp_path):
    store = ReceiverStore(tmp_path)
    store.put({"order_id": "old-order", "result": {"value": 1}})
    store.results.clear()
    store.put({"order_id": "new-order", "result": {"value": 2}})

    fetched = store.get("old-order")
    assert fetched is not None
    assert fetched["order_id"] == "old-order"
    assert store.latest()["order_id"] == "new-order"


def test_receiver_returns_404_for_unknown_order(tmp_path):
    port = _free_port()
    ReceiverHandler.task_type = "low_latency_video_pipeline"
    ReceiverHandler.store = ReceiverStore(tmp_path)
    start_server(port, ReceiverHandler)

    status, body = _request_json("GET", port, "/orders/missing-order")
    assert status == 404
    assert body["order_id"] == "missing-order"
