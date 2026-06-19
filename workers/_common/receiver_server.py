"""Small HTTP receiver for user-controlled endpoint demos."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html import escape
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from _common.http_server import start_server


@dataclass(frozen=True)
class ReceiverConfig:
    task_type: str
    port: int
    node_alias: str | None = None
    topology_node_id: str | None = None
    business_ip: str | None = None
    business_ipv6: str | None = None


class ReceiverStore:
    """In-memory plus optional JSON-file persistence keyed by order_id."""

    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir
        self.results: dict[str, dict[str, Any]] = {}
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def put(self, payload: dict[str, Any]) -> dict[str, Any]:
        order_id = str(payload.get("order_id") or payload.get("task_order_id") or "unknown-order")
        received_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        event_type = str(payload.get("event_type") or payload.get("status") or "final").lower()
        existing = self.get(order_id) or {"order_id": order_id, "events": []}
        events = existing.get("events") if isinstance(existing.get("events"), list) else []
        if event_type == "progress":
            event = {
                "received_at": received_at,
                "payload": payload,
            }
            events.append(event)
            already_completed = existing.get("status") == "completed" and isinstance(existing.get("payload"), dict)
            record = {
                **existing,
                "order_id": order_id,
                "received_at": existing.get("received_at") or received_at,
                "updated_at": received_at,
                "status": "completed" if already_completed else "running",
                "events": events[-120:],
                "payload": existing.get("payload") if already_completed else _merge_progress_payload(existing.get("payload"), payload),
            }
        else:
            record = {
                **existing,
                "order_id": order_id,
                "received_at": received_at,
                "updated_at": received_at,
                "status": "completed",
                "events": events[-120:],
                "payload": payload,
                "final_payload": payload,
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
        stored_records = dict(self.results)
        for record_path in self.storage_dir.glob("*.json"):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            order_id = str(record.get("order_id") or record_path.stem)
            stored_records.setdefault(order_id, record)
        return {
            "status": "ok",
            "stored_orders": sorted(stored_records.keys()),
            "stored_records": stored_records,
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
    config = ReceiverConfig(task_type="generic", port=9000)

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

    def _send_bytes(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
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
        self._send_json(200, {**record, "record_status": record.get("status"), "status": "ok", "task_type": ReceiverHandler.task_type})

    def do_GET(self) -> None:
        if ReceiverHandler.store is None:
            self._send_json(500, {"error": "receiver store is not initialized"})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            query = parse_qs(parsed.query)
            selected_order_id = (query.get("order_id") or [""])[0].strip()
            self._send_html(
                200,
                _render_receiver_page(
                    ReceiverHandler.task_type,
                    ReceiverHandler.store.summary(),
                    ReceiverHandler.config,
                    selected_order_id=selected_order_id or None,
                ),
            )
            return
        if parsed.path in {"/result", "/latest"}:
            self._send_json(200, {"task_type": ReceiverHandler.task_type, **ReceiverHandler.store.summary()})
            return
        if parsed.path.startswith("/assets/"):
            asset = _resolve_receiver_asset(parsed.path.removeprefix("/assets/"))
            if asset is None:
                self._send_json(404, {"error": "asset not found"})
                return
            content_type = mimetypes.guess_type(str(asset))[0] or "application/octet-stream"
            if asset.suffix.lower() == ".mp4":
                content_type = "video/mp4"
            self._send_bytes(200, asset.read_bytes(), content_type)
            return
        prefix = "/orders/"
        if parsed.path.startswith(prefix):
            order_id = unquote(parsed.path[len(prefix):].strip("/"))
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
    ReceiverHandler.config = ReceiverConfig(
        task_type=task_type,
        port=port,
        node_alias=_env("ENDPOINT_NODE_ALIAS", "NODE_ALIAS", "TOPOLOGY_ALIAS"),
        topology_node_id=_env("ENDPOINT_TOPOLOGY_NODE_ID", "TOPOLOGY_NODE_ID"),
        business_ip=_env("ENDPOINT_BUSINESS_IP", "BUSINESS_IP"),
        business_ipv6=_env("ENDPOINT_BUSINESS_IPV6", "BUSINESS_IPV6"),
    )
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


def _render_receiver_page(
    task_type: str,
    summary: dict[str, Any],
    config: ReceiverConfig | None = None,
    *,
    selected_order_id: str | None = None,
) -> str:
    config = config or ReceiverConfig(task_type=task_type, port=9000)
    latest = _select_record(summary, selected_order_id)
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
    status_text = "已完成" if latest.get("status") == "completed" else "运行中"
    stored_orders = _render_order_list(summary.get("stored_orders", []), selected_order_id or latest.get("order_id"))
    image_html = ""
    if isinstance(preview_url, str) and _is_safe_raster_data_url(preview_url):
        image_html = f'<img class="preview" src="{escape(preview_url, quote=True)}" alt="视频推理画框预览" />'
    task_title = _task_title(task_type)
    result_cards = _render_result_cards(task_type, result, payload.get("metric_key"))
    callback_url = _callback_url(config)
    receiver_info = _render_receiver_info(config, callback_url, order_id)
    evidence_html = _render_video_evidence(task_type, result)
    preview_gallery_html = (
        f"""
          <div class="inline-evidence">
            <h3>抽样检测帧</h3>
            <div class="muted">下方展示本次任务已处理视频帧中的代表性检测结果；鼠标悬停可查看帧序号、单帧时延和识别目标。</div>
            {_render_preview_frame_gallery(result)}
          </div>
        """
        if task_type == "low_latency_video_pipeline"
        else ""
    )
    auto_refresh = "" if latest.get("status") == "completed" else '<meta http-equiv="refresh" content="2" />'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  {auto_refresh}
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>用户端结果接收器</title>
  <style>
    :root {{
      --bg: #f3f7fb;
      --card: #ffffff;
      --ink: #142033;
      --subtle: #1f2f46;
      --line: #d8e2ef;
      --blue: #1d4ed8;
      --blue-soft: #eaf2ff;
      --green-soft: #e9f8ef;
      --green: #166534;
    }}
    body {{
      margin: 0;
      font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(29, 78, 216, 0.12), transparent 32rem),
        linear-gradient(180deg, #f8fbff 0%, var(--bg) 100%);
      color: var(--ink);
    }}
    main {{
      max-width: 1120px;
      margin: 32px auto;
      padding: 0 20px 40px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 16px 36px rgba(18, 38, 63, 0.08);
      padding: 24px;
      margin-bottom: 18px;
    }}
    .hero {{
      background: linear-gradient(135deg, #ffffff 0%, #eef6ff 100%);
      border-color: #c9daf4;
    }}
    h1 {{ margin: 0 0 10px; font-size: 30px; letter-spacing: -0.02em; }}
    h2 {{ margin: 0 0 14px; font-size: 21px; }}
    .muted {{ color: var(--subtle); line-height: 1.7; }}
    h3 {{ margin: 18px 0 8px; font-size: 17px; }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 12px;
      padding: 6px 10px;
      border-radius: 999px;
      background: var(--green-soft);
      color: var(--green);
      font-weight: 700;
      font-size: 13px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .metric {{
      border-radius: 12px;
      background: var(--blue-soft);
      padding: 14px;
      min-width: 0;
    }}
    .metric span {{ display: block; color: var(--subtle); font-size: 13px; }}
    .metric strong {{
      display: block;
      font-size: 18px;
      margin-top: 6px;
      overflow-wrap: anywhere;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.6fr);
      gap: 18px;
      align-items: start;
    }}
    .preview {{
      width: 100%;
      max-height: 520px;
      object-fit: contain;
      border-radius: 12px;
      background: #0f172a;
    }}
    .video-player {{
      width: 100%;
      max-height: 360px;
      border-radius: 12px;
      background: #0f172a;
    }}
    .thumb-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    .thumb-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fff;
      overflow: hidden;
    }}
    .thumb-image {{
      width: 100%;
      height: 150px;
      object-fit: cover;
      display: block;
      background: #0f172a;
    }}
    .thumb-meta {{
      padding: 10px 12px;
      line-height: 1.6;
      color: #142033;
      font-size: 13px;
      font-weight: 600;
    }}
    .latency-chart {{
      width: 100%;
      min-height: 170px;
      border-radius: 14px;
      background: #f8fbff;
      border: 1px solid var(--line);
    }}
    .detection-list {{
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }}
    .detection-item {{
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      background: #fff;
      color: #142033;
      line-height: 1.7;
    }}
    .inline-evidence {{
      margin-top: 18px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }}
    .order-list {{
      display: grid;
      gap: 8px;
      max-height: 300px;
      overflow: auto;
    }}
    .order-link {{
      display: block;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      color: var(--blue);
      text-decoration: none;
      overflow-wrap: anywhere;
      background: #fff;
    }}
    .order-link.active {{
      border-color: var(--blue);
      background: var(--blue-soft);
      font-weight: 700;
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
    code {{
      background: rgba(15, 23, 42, 0.08);
      border-radius: 6px;
      padding: 2px 6px;
    }}
    @media (max-width: 840px) {{
      .layout {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 25px; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="card hero">
      <div class="pill">目的端用户设备正在接收结果</div>
      <h1>{task_title}结果接收页</h1>
      <div class="muted">本页面运行在目的端容器内，用固定端口接收 compute 节点推送的随路计算结果。固定端口可连续接收多个工单，并按工单 ID 区分展示。</div>
      <div class="grid">
        <div class="metric"><span>工单 ID</span><strong>{order_id}</strong></div>
        <div class="metric"><span>接收状态</span><strong>{status_text}</strong></div>
        <div class="metric"><span>业务类型</span><strong>{task_title}</strong></div>
        <div class="metric"><span>接收时间</span><strong>{received_at}</strong></div>
        <div class="metric"><span>当前指标</span><strong>{metric_key}: {escape(str(metric_value if metric_value is not None else "-"))}</strong></div>
      </div>
    </section>
    <section class="card">
      <h2>本端接收信息</h2>
      {receiver_info}
    </section>
    <div class="layout">
      <div>
        <section class="card">
          <h2>结果预览</h2>
          {image_html or '<div class="muted">暂无图片预览。矩阵计算任务会展示结果数字；视频推理任务回调后会展示带中文标签和检测框的预览图。</div>'}
          {preview_gallery_html}
          <div class="grid">{result_cards}</div>
        </section>
        {evidence_html}
        <section class="card">
          <h2>最近回调数据</h2>
          <div class="muted">用于排查和复核。专家演示时通常只看上方预览和关键结果。</div>
          <pre>{raw_json}</pre>
        </section>
      </div>
      <aside>
        <section class="card">
          <h2>已接收工单</h2>
          <div class="muted">同一固定端口可接收多个工单，点击工单 ID 可切换查看。</div>
          <div class="order-list">{stored_orders}</div>
        </section>
      </aside>
    </div>
  </main>
</body>
</html>"""


def _select_record(summary: dict[str, Any], selected_order_id: str | None) -> dict[str, Any]:
    if selected_order_id:
        latest = summary.get("latest")
        if isinstance(latest, dict) and latest.get("order_id") == selected_order_id:
            return latest
        stored = summary.get("stored_records")
        if isinstance(stored, dict):
            record = stored.get(selected_order_id)
            if isinstance(record, dict):
                return record
    latest = summary.get("latest")
    return latest if isinstance(latest, dict) else {}


def _merge_progress_payload(existing_payload: Any, progress_payload: dict[str, Any]) -> dict[str, Any]:
    base = dict(existing_payload) if isinstance(existing_payload, dict) else {}
    merged = {**base, **progress_payload}
    base_result = base.get("result") if isinstance(base.get("result"), dict) else {}
    progress_result = progress_payload.get("result") if isinstance(progress_payload.get("result"), dict) else {}
    merged_result = {**base_result, **progress_result}
    for key, limit in (("samples", 240), ("preview_frames", 8), ("detections", 40)):
        merged_result[key] = _merge_result_list(base_result.get(key), progress_result.get(key), limit=limit)
    if merged_result:
        merged["result"] = merged_result
    return merged


def _merge_result_list(existing: Any, incoming: Any, *, limit: int) -> list[Any]:
    items: list[Any] = []
    if isinstance(existing, list):
        items.extend(existing)
    if isinstance(incoming, list):
        items.extend(incoming)
    deduped: list[Any] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            key = str(item.get("frame_index") or item.get("label") or item)
        else:
            key = str(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[-limit:]


def _render_order_list(stored_orders: Any, selected_order_id: Any) -> str:
    if not isinstance(stored_orders, list) or not stored_orders:
        return '<div class="muted">暂无已接收工单。</div>'
    selected = str(selected_order_id or "")
    items = []
    for item in sorted((str(order) for order in stored_orders), reverse=True):
        active = " active" if item == selected else ""
        items.append(
            f'<a class="order-link{active}" href="/?order_id={escape(item, quote=True)}">{escape(item)}</a>'
        )
    return "".join(items)


def _render_receiver_info(config: ReceiverConfig, callback_url: str, order_id: str) -> str:
    return f"""
      <div class="grid">
        <div class="metric"><span>节点别名</span><strong>{escape(config.node_alias or "未注入")}</strong></div>
        <div class="metric"><span>拓扑节点 ID</span><strong>{escape(config.topology_node_id or "未注入")}</strong></div>
        <div class="metric"><span>数据面 IPv6</span><strong>{escape(config.business_ipv6 or "未注入")}</strong></div>
        <div class="metric"><span>数据面 IPv4</span><strong>{escape(config.business_ip or "未注入")}</strong></div>
        <div class="metric"><span>监听端口</span><strong>{escape(str(config.port))}</strong></div>
        <div class="metric"><span>回调地址</span><strong>{escape(callback_url)}</strong></div>
        <div class="metric"><span>当前工单查询接口</span><strong>/orders/{order_id}</strong></div>
      </div>
    """


def _render_result_cards(task_type: str, result: dict[str, Any], metric_key: Any) -> str:
    cards: list[tuple[str, str]] = []
    if task_type == "high_throughput_matmul":
        cards.extend(
            [
                ("有效计算性能", _format_number(result.get("effective_gflops"), " GFLOPS")),
                ("矩阵规模", _format_plain(result.get("matrix_size"))),
                ("批次数", _format_plain(result.get("batch_count"))),
                ("计算后端", _format_plain(result.get("backend") or result.get("actual_backend"))),
            ]
        )
    elif task_type == "low_latency_video_pipeline":
        cards.extend(
            [
                ("P90 推理时延", _format_number(result.get("frame_latency_p90_ms"), " ms")),
                ("平均推理时延", _format_number(result.get("frame_latency_avg_ms"), " ms")),
                ("预览帧序号", _format_plain(result.get("annotated_frame_index"))),
                ("预览帧时延", _format_number(result.get("annotated_frame_latency_ms"), " ms")),
                ("中文分类", _format_plain(result.get("top_label_zh") or result.get("top_label"))),
                ("推理后端", _format_plain(result.get("detector_backend") or result.get("backend"))),
                ("运行设备", _format_plain(result.get("device"))),
            ]
        )
    else:
        cards.append((str(metric_key or "业务指标"), _format_plain(result.get(str(metric_key)))))
    return "".join(
        f'<div class="metric"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in cards
        if value != "-"
    )


def _render_video_evidence(task_type: str, result: dict[str, Any]) -> str:
    if task_type != "low_latency_video_pipeline":
        return ""
    video_asset = _safe_asset_name(str(result.get("video_asset") or "bottle-detection.mp4"))
    video_html = ""
    if video_asset:
        video_html = f"""
          <section class="card">
            <h2>原始测试视频</h2>
            <div class="muted">用于说明本次视频推理的输入来源。compute 节点抽帧检测后，将带画框的结果推送到本页面。</div>
            <video class="video-player" controls muted preload="metadata" src="/assets/{escape(video_asset, quote=True)}"></video>
          </section>
        """
    return (
        video_html
        + f"""
          <section class="card">
            <h2>推理时延趋势</h2>
            {_render_latency_chart(result.get("samples"))}
          </section>
          <section class="card">
            <h2>检测目标列表</h2>
            {_render_detection_list(result.get("detections"))}
          </section>
        """
    )


def _render_latency_chart(samples: Any) -> str:
    if not isinstance(samples, list) or not samples:
        return '<div class="muted">暂无时延样本。任务运行中会持续刷新。</div>'
    points: list[tuple[int, float]] = []
    for item in samples[:60]:
        if not isinstance(item, dict):
            continue
        try:
            points.append((int(item.get("frame_index", len(points))), float(item.get("latency_ms", 0.0))))
        except (TypeError, ValueError):
            continue
    if not points:
        return '<div class="muted">暂无可展示的时延样本。</div>'
    max_latency = max(value for _, value in points) or 1.0
    width = 720
    height = 190
    left = 42
    top = 18
    plot_width = width - left - 24
    plot_height = height - top - 34
    step = plot_width / max(1, len(points) - 1)
    coords = []
    labels = []
    for idx, (frame_index, latency) in enumerate(points):
        x = left + idx * step
        y = top + plot_height - (latency / max_latency) * plot_height
        coords.append(f"{x:.1f},{y:.1f}")
        labels.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#1d4ed8"><title>帧 {frame_index}: {latency:.2f} ms</title></circle>'
        )
    recent = points[-1]
    return f"""
      <svg class="latency-chart" viewBox="0 0 {width} {height}" role="img" aria-label="推理时延趋势">
        <line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#9fb1c7" />
        <line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#9fb1c7" />
        <polyline points="{' '.join(coords)}" fill="none" stroke="#1d4ed8" stroke-width="3" />
        {''.join(labels)}
        <text x="{left}" y="15" fill="#334155" font-size="13">最高 {max_latency:.2f} ms</text>
        <text x="{left}" y="{height - 8}" fill="#334155" font-size="13">最近：帧 {recent[0]}，{recent[1]:.2f} ms</text>
      </svg>
    """


def _render_preview_frame_gallery(result: dict[str, Any]) -> str:
    frames = result.get("preview_frames")
    if not isinstance(frames, list) or not frames:
        preview_url = result.get("annotated_frame_data_url")
        if isinstance(preview_url, str) and _is_safe_raster_data_url(preview_url):
            frames = [
                {
                    "frame_index": result.get("annotated_frame_index", "-"),
                    "latency_ms": result.get("annotated_frame_latency_ms", 0.0),
                    "top_label_zh": result.get("top_label_zh") or result.get("top_label") or "-",
                    "data_url": preview_url,
                }
            ]
        else:
            return '<div class="muted">暂无抽帧图片。任务运行中会逐步展示检测画框。</div>'
    cards = []
    total_frames = result.get("measured_frames")
    p90_latency = result.get("frame_latency_p90_ms")
    for item in frames[:8]:
        if not isinstance(item, dict):
            continue
        data_url = item.get("data_url")
        if not isinstance(data_url, str) or not _is_safe_raster_data_url(data_url):
            continue
        frame_index = escape(str(item.get("frame_index", "-")))
        latency_ms = _format_number(item.get("latency_ms"), " ms")
        label = escape(str(item.get("top_label_zh") or item.get("top_label") or "-"))
        confidence = item.get("confidence")
        confidence_text = f"，置信度 {float(confidence):.2f}" if isinstance(confidence, int | float) else ""
        title_parts = [f"第 {frame_index} 帧", f"推理时延 {latency_ms}", f"识别目标 {label}"]
        if isinstance(total_frames, int | float):
            title_parts.append(f"本次有效推理 {int(total_frames)} 帧")
        if isinstance(p90_latency, int | float):
            title_parts.append(f"P90 {float(p90_latency):.2f} ms")
        title = "；".join(title_parts)
        cards.append(
            f"""
            <div class="thumb-card">
              <img class="thumb-image" src="{escape(data_url, quote=True)}" alt="帧 {frame_index} 检测画框" title="{escape(title, quote=True)}" />
              <div class="thumb-meta">帧 {frame_index}<br />推理时延 {escape(latency_ms)}<br />目标 {label}{escape(confidence_text)}</div>
            </div>
            """
        )
    if not cards:
        return '<div class="muted">暂无安全可展示的抽帧图片。</div>'
    return f'<div class="thumb-grid">{"".join(cards)}</div>'


def _render_detection_list(detections: Any) -> str:
    if not isinstance(detections, list) or not detections:
        return '<div class="muted">暂无检测目标。</div>'
    items = []
    for detection in detections[:20]:
        if not isinstance(detection, dict):
            continue
        label = escape(str(detection.get("label_zh") or detection.get("label") or "-"))
        confidence = detection.get("confidence")
        bbox = detection.get("bbox_xyxy")
        bbox_text = f"bbox: {bbox}" if isinstance(bbox, list) else "bbox: -"
        confidence_text = f"{float(confidence):.2f}" if isinstance(confidence, int | float) else "-"
        items.append(
            f'<div class="detection-item"><strong>{label}</strong>，置信度 {escape(confidence_text)}，{escape(bbox_text)}</div>'
        )
    return f'<div class="detection-list">{"".join(items)}</div>' if items else '<div class="muted">暂无检测目标。</div>'


def _format_number(value: Any, suffix: str) -> str:
    if isinstance(value, int | float):
        formatted = f"{value:.3f}".rstrip("0").rstrip(".")
        return f"{formatted}{suffix}"
    return "-"


def _format_plain(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _task_title(task_type: str) -> str:
    return {
        "high_throughput_matmul": "矩阵乘法计算任务",
        "low_latency_video_pipeline": "视频 AI 推理任务",
    }.get(task_type, task_type)


def _callback_url(config: ReceiverConfig) -> str:
    host = config.business_ipv6 or config.business_ip
    if not host:
        return f"本机监听端口 {config.port}，未注入数据面地址"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{config.port}/callback"


def _is_safe_raster_data_url(value: str) -> bool:
    return value.startswith(
        (
            "data:image/jpeg;",
            "data:image/jpg;",
            "data:image/png;",
            "data:image/webp;",
            "data:image/gif;",
        )
    )


def _safe_asset_name(value: str) -> str | None:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    if len(candidate.parts) != 1:
        return None
    if candidate.suffix.lower() not in {".mp4", ".webm", ".mov"}:
        return None
    return candidate.name


def _receiver_asset_roots() -> list[Path]:
    roots = []
    for name in ("ENDPOINT_ASSET_DIR", "VIDEO_ASSET_DIR"):
        configured = os.environ.get(name)
        if configured:
            roots.append(Path(configured))
    roots.extend(
        [
            Path("/app/assets"),
            Path(__file__).resolve().parents[1] / "low-latency-video" / "assets",
        ]
    )
    return roots


def _resolve_receiver_asset(raw_name: str) -> Path | None:
    name = _safe_asset_name(unquote(raw_name))
    if not name:
        return None
    for root in _receiver_asset_roots():
        try:
            root_resolved = root.resolve()
            candidate = (root_resolved / name).resolve()
            if not candidate.is_relative_to(root_resolved):
                continue
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None
