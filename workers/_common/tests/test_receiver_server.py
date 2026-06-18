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
from _common.receiver_server import ReceiverConfig, ReceiverHandler, ReceiverStore  # noqa: E402


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


def _request_bytes(method: str, port: int, path: str) -> tuple[int, str, bytes]:
    conn = HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request(method, path)
        response = conn.getresponse()
        return response.status, response.getheader("Content-Type", ""), response.read()
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
    ReceiverHandler.config = ReceiverConfig(
        task_type="low_latency_video_pipeline",
        port=9100,
        node_alias="h2",
        topology_node_id="h18015002",
        business_ip="10.112.253.42",
        business_ipv6="2001:db8::2",
    )
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
                "frame_latency_avg_ms": 15.1,
                "annotated_frame_latency_ms": 17.9,
                "annotated_frame_index": 60,
                "top_label_zh": "车辆",
                "video_asset": "bottle-detection.mp4",
                "samples": [
                    {"frame_index": 30, "latency_ms": 12.1, "label": "car", "confidence": 0.91},
                    {"frame_index": 60, "latency_ms": 18.6, "label": "car", "confidence": 0.87},
                ],
                "preview_frames": [
                    {
                        "frame_index": 30,
                        "latency_ms": 12.1,
                        "top_label_zh": "车辆",
                        "data_url": "data:image/jpeg;base64,frame30",
                    },
                    {
                        "frame_index": 60,
                        "latency_ms": 18.6,
                        "top_label_zh": "车辆",
                        "data_url": "data:image/jpeg;base64,frame60",
                    },
                ],
                "detections": [
                    {
                        "label": "car",
                        "label_zh": "车辆",
                        "confidence": 0.91,
                        "bbox_xyxy": [10, 20, 80, 120],
                    }
                ],
                "annotated_frame_data_url": "data:image/jpeg;base64,abc123",
            },
        },
    )

    status, content_type, body = _request_text("GET", port, "/")
    assert status == 200
    assert "text/html" in content_type
    assert "用户端结果接收器" in body
    assert "video-order-1" in body
    assert "P90 推理时延" in body
    assert "18.6 ms" in body
    assert "车辆" in body
    assert "h2" in body
    assert "h18015002" in body
    assert "2001:db8::2" in body
    assert "9100" in body
    assert body.index("本端接收信息") < body.index("结果预览")
    assert "原始测试视频" in body
    assert "/assets/bottle-detection.mp4" in body
    assert "抽帧检测证据" in body
    assert "推理时延趋势" in body
    assert "帧 30" in body
    assert "帧 60" in body
    assert "12.1 ms" in body
    assert "18.6 ms" in body
    assert "检测目标列表" in body
    assert "bbox: [10, 20, 80, 120]" in body
    assert "/orders/video-order-1" in body
    assert '<img class="preview" src="data:image/jpeg;base64,abc123"' in body
    assert '<img class="thumb-image" src="data:image/jpeg;base64,frame30"' in body


def test_receiver_homepage_supports_switching_between_orders_on_fixed_port(tmp_path):
    port = _free_port()
    ReceiverHandler.task_type = "high_throughput_matmul"
    ReceiverHandler.config = ReceiverConfig(
        task_type="high_throughput_matmul",
        port=9000,
        node_alias="h1",
        topology_node_id="h18001001",
        business_ip="10.112.126.124",
    )
    ReceiverHandler.store = ReceiverStore(tmp_path)
    start_server(port, ReceiverHandler)

    _request_json(
        "POST",
        port,
        "/callback",
        {
            "order_id": "matmul-order-old",
            "metric_key": "effective_gflops",
            "result": {"effective_gflops": 91.2, "matrix_size": 2048, "batch_count": 4},
        },
    )
    _request_json(
        "POST",
        port,
        "/callback",
        {
            "order_id": "matmul-order-new",
            "metric_key": "effective_gflops",
            "result": {"effective_gflops": 122.5, "matrix_size": 4096, "batch_count": 2},
        },
    )

    status, content_type, body = _request_text("GET", port, "/")
    assert status == 200
    assert "text/html" in content_type
    assert "固定端口可连续接收多个工单" in body
    assert "/?order_id=matmul-order-old" in body
    assert "/?order_id=matmul-order-new" in body
    assert "matmul-order-new" in body
    assert "有效计算性能" in body
    assert "122.5 GFLOPS" in body
    assert "矩阵规模" in body
    assert "4096" in body

    status, content_type, old_body = _request_text("GET", port, "/?order_id=matmul-order-old")
    assert status == 200
    assert "text/html" in content_type
    assert "matmul-order-old" in old_body
    assert "91.2 GFLOPS" in old_body
    assert "matmul-order-new" in old_body


def test_receiver_progress_events_do_not_replace_final_payload(tmp_path):
    store = ReceiverStore(tmp_path)

    first = store.put(
        {
            "event_type": "progress",
            "order_id": "video-order-progress",
            "metric_key": "frame_latency_p90_ms",
            "result": {
                "samples": [{"frame_index": 30, "latency_ms": 11.2}],
                "preview_frames": [
                    {
                        "frame_index": 30,
                        "latency_ms": 11.2,
                        "top_label_zh": "瓶子",
                        "data_url": "data:image/jpeg;base64,progress30",
                    }
                ],
            },
        }
    )
    assert first["status"] == "running"
    assert len(first["events"]) == 1
    assert first["payload"]["result"]["samples"][0]["frame_index"] == 30

    final = store.put(
        {
            "event_type": "final",
            "order_id": "video-order-progress",
            "metric_key": "frame_latency_p90_ms",
            "result": {
                "frame_latency_p90_ms": 18.6,
                "samples": [{"frame_index": 60, "latency_ms": 18.6}],
                "preview_frames": [
                    {
                        "frame_index": 60,
                        "latency_ms": 18.6,
                        "top_label_zh": "瓶子",
                        "data_url": "data:image/jpeg;base64,final60",
                    }
                ],
            },
        }
    )

    assert final["status"] == "completed"
    assert len(final["events"]) == 1
    assert final["payload"]["result"]["frame_latency_p90_ms"] == 18.6
    assert final["payload"]["result"]["samples"][0]["frame_index"] == 60
    assert final["final_payload"]["result"]["frame_latency_p90_ms"] == 18.6


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


def test_receiver_serves_only_safe_video_assets(tmp_path, monkeypatch):
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    (asset_dir / "bottle-detection.mp4").write_bytes(b"demo-video")
    monkeypatch.setenv("ENDPOINT_ASSET_DIR", str(asset_dir))

    port = _free_port()
    ReceiverHandler.task_type = "low_latency_video_pipeline"
    ReceiverHandler.store = ReceiverStore(tmp_path / "store")
    start_server(port, ReceiverHandler)

    status, content_type, body = _request_bytes("GET", port, "/assets/bottle-detection.mp4")
    assert status == 200
    assert content_type == "video/mp4"
    assert body == b"demo-video"

    status, _, _ = _request_bytes("GET", port, "/assets/../secret.mp4")
    assert status == 404


def test_receiver_returns_404_for_unknown_order(tmp_path):
    port = _free_port()
    ReceiverHandler.task_type = "low_latency_video_pipeline"
    ReceiverHandler.store = ReceiverStore(tmp_path)
    start_server(port, ReceiverHandler)

    status, body = _request_json("GET", port, "/orders/missing-order")
    assert status == 404
    assert body["order_id"] == "missing-order"
