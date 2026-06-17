"""Small HTTP receiver for user-controlled endpoint demos."""

from __future__ import annotations

import argparse
from html import escape
import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import time
from typing import Any
from urllib.parse import unquote

from _common.http_server import start_server


class ReceiverStore:
    """In-memory plus optional JSON-file persistence keyed by order_id."""

    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir
        self.results: dict[str, dict[str, Any]] = {}
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def put(self, payload: dict[str, Any]) -> dict[str, Any]:
        order_id = str(payload.get("order_id") or payload.get("task_order_id") or "unknown-order")
        record = {
            "order_id": order_id,
            "received_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "payload": payload,
        }
        self.results[order_id] = record
        self._write_record(order_id, record)
        return record

    def get(self, order_id: str) -> dict[str, Any] | None:
        if order_id in self.results:
            return self.results[order_id]
        path = self._record_path(order_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def latest(self) -> dict[str, Any] | None:
        if self.results:
            return next(reversed(self.results.values()))
        records = sorted(self.storage_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not records:
            return None
        record = json.loads(records[0].read_text(encoding="utf-8"))
        self.results[str(record.get("order_id") or "unknown-order")] = record
        return record

    def summary(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "stored_orders": sorted(self.results.keys()),
            "latest": self.latest(),
        }

    def _record_path(self, order_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in order_id)
        return self.storage_dir / f"{safe}.json"

    def _write_record(self, order_id: str, record: dict[str, Any]) -> None:
        self._record_path(order_id).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


class ReceiverHandler(BaseHTTPRequestHandler):
    store: ReceiverStore | None = None
    task_type = "generic"

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        if self.path != "/callback":
            self._send_json(404, {"error": "not found"})
            return
        content_length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": f"invalid json: {exc}"})
            return
        if ReceiverHandler.store is None:
            self._send_json(500, {"error": "receiver store is not initialized"})
            return
        record = ReceiverHandler.store.put(payload)
        self._send_json(200, {"status": "ok", "task_type": ReceiverHandler.task_type, **record})

    def do_GET(self) -> None:
        if ReceiverHandler.store is None:
            self._send_json(500, {"error": "receiver store is not initialized"})
            return
        if self.path == "/":
            self._send_html(200, _render_receiver_page(ReceiverHandler.task_type, ReceiverHandler.store.summary()))
            return
        if self.path in {"/result", "/latest"}:
            self._send_json(200, {"task_type": ReceiverHandler.task_type, **ReceiverHandler.store.summary()})
            return
        prefix = "/orders/"
        if self.path.startswith(prefix):
            order_id = unquote(self.path[len(prefix):].strip("/"))
            record = ReceiverHandler.store.get(order_id)
            if record is None:
                self._send_json(404, {"error": "order result not found", "order_id": order_id})
                return
            self._send_json(200, {"task_type": ReceiverHandler.task_type, **record})
            return
        self._send_json(404, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:
        pass


def run_receiver(*, port: int, task_type: str, storage_dir: str) -> None:
    ReceiverHandler.task_type = task_type
    ReceiverHandler.store = ReceiverStore(Path(storage_dir))
    start_server(port, ReceiverHandler)
    print(
        f"USER_ENDPOINT_RECEIVER_READY task_type={task_type} port={port} storage_dir={storage_dir}",
        flush=True,
    )
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return


def main(task_type: str) -> int:
    parser = argparse.ArgumentParser(description=f"Start {task_type} user endpoint receiver")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--storage-dir", default="/tmp/user-endpoint-results")
    args = parser.parse_args()
    run_receiver(port=args.port, task_type=task_type, storage_dir=args.storage_dir)
    return 0


def _render_receiver_page(task_type: str, summary: dict[str, Any]) -> str:
    latest = summary.get("latest") or {}
    payload = latest.get("payload") if isinstance(latest, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    result = payload.get("result") if isinstance(payload, dict) else {}
    result = result if isinstance(result, dict) else {}
    order_id = escape(str(latest.get("order_id") or payload.get("order_id") or "暂无结果"))
    metric_key = escape(str(payload.get("metric_key") or "-"))
    metric_value = result.get(payload.get("metric_key", ""))
    if metric_value is None and payload.get("metric_key") == "effective_gflops":
        metric_value = result.get("effective_gflops")
    if metric_value is None and payload.get("metric_key") == "frame_latency_p90_ms":
        metric_value = result.get("frame_latency_p90_ms")
    preview_url = result.get("annotated_frame_data_url")
    raw_json = escape(json.dumps(payload or {}, ensure_ascii=False, indent=2))
    top_label_zh = escape(str(result.get("top_label_zh") or result.get("top_label") or "-"))
    received_at = escape(str(latest.get("received_at") or "-"))
    stored_orders = ", ".join(str(item) for item in summary.get("stored_orders", [])) or "-"
    image_html = ""
    safe_image_prefixes = (
        "data:image/jpeg;",
        "data:image/jpg;",
        "data:image/png;",
        "data:image/webp;",
        "data:image/gif;",
    )
    if isinstance(preview_url, str) and preview_url.startswith(safe_image_prefixes):
        image_html = f'<img class="preview" src="{escape(preview_url, quote=True)}" alt="视频推理画框预览" />'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>用户端结果接收器</title>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f8fb;
      color: #172033;
    }}
    main {{
      max-width: 960px;
      margin: 32px auto;
      padding: 0 20px 40px;
    }}
    .card {{
      background: white;
      border: 1px solid #dfe6f1;
      border-radius: 16px;
      box-shadow: 0 12px 30px rgba(18, 38, 63, 0.08);
      padding: 24px;
      margin-bottom: 18px;
    }}
    h1 {{ margin: 0 0 10px; font-size: 26px; }}
    .muted {{ color: #4c5b73; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .metric {{
      border-radius: 12px;
      background: #eef4ff;
      padding: 14px;
    }}
    .metric strong {{ display: block; font-size: 18px; margin-top: 6px; }}
    .preview {{
      width: 100%;
      max-height: 520px;
      object-fit: contain;
      border-radius: 12px;
      background: #0f172a;
    }}
    pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: #0f172a;
      color: #e5edf9;
      border-radius: 12px;
      padding: 16px;
      max-height: 420px;
      overflow: auto;
    }}
  </style>
</head>
<body>
  <main>
    <section class="card">
      <h1>用户端结果接收器</h1>
      <div class="muted">用于演示目的端用户设备接收随路计算结果。JSON 接口：<code>/callback</code>、<code>/latest</code>、<code>/orders/&lt;order_id&gt;</code></div>
      <div class="grid">
        <div class="metric">业务类型<strong>{escape(task_type)}</strong></div>
        <div class="metric">工单 ID<strong>{order_id}</strong></div>
        <div class="metric">接收时间<strong>{received_at}</strong></div>
        <div class="metric">指标<strong>{metric_key}: {escape(str(metric_value if metric_value is not None else "-"))}</strong></div>
        <div class="metric">中文分类<strong>{top_label_zh}</strong></div>
      </div>
    </section>
    <section class="card">
      <h2>结果预览</h2>
      {image_html or '<div class="muted">暂无图片预览。矩阵计算任务可在下方 JSON 中查看结果数值；视频推理任务回调后会显示带框预览图。</div>'}
    </section>
    <section class="card">
      <h2>已接收工单</h2>
      <div class="muted">{escape(stored_orders)}</div>
    </section>
    <section class="card">
      <h2>最近回调 JSON</h2>
      <pre>{raw_json}</pre>
    </section>
  </main>
</body>
</html>"""
