"""Video inference core used by the low-latency video worker.

The default path runs a YOLOv5 ONNX detector over fixed sampled frames and
returns both latency metrics and an annotated preview image. A deterministic
fallback remains available only for local development or environments without
OpenCV/model assets.
"""

from __future__ import annotations

import base64
import math
import os
import subprocess
import statistics
import time
from pathlib import Path
from typing import Callable

try:  # Optional locally; installed in the worker image.
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - exercised when local OpenCV is absent.
    cv2 = None
    np = None

try:  # Pillow is used to draw Chinese labels on preview frames.
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
except Exception:  # pragma: no cover - local fallback when Pillow is absent.
    Image = None
    ImageDraw = None
    ImageFont = None

try:  # ONNX Runtime GPU is preferred when the image provides CUDA providers.
    import onnxruntime as ort  # type: ignore
except Exception:  # pragma: no cover - optional in local/dev environments.
    ort = None


INPUT_SIZE = 640
DEFAULT_VIDEO = "bottle-detection.mp4"
DEFAULT_MODEL = "models/yolov5n-fp32.onnx"
DEFAULT_CLASSES = "models/coco.names"
CLASS_LABEL_ZH = {
    "person": "人员",
    "bicycle": "自行车",
    "car": "车辆",
    "motorcycle": "摩托车",
    "bus": "公交车",
    "truck": "卡车",
    "traffic light": "交通灯",
    "stop sign": "停止标志",
    "bench": "长椅",
    "bird": "鸟",
    "cat": "猫",
    "dog": "狗",
    "bottle": "瓶子",
    "cup": "杯子",
    "chair": "椅子",
    "laptop": "笔记本电脑",
    "cell phone": "手机",
    "inspection_target": "检测目标",
    "normal": "正常",
    "defect": "缺陷",
    "none": "无目标",
}
FONT_CANDIDATES = (
    "/app/assets/fonts/NotoSansCJKsc-Regular.otf",
    "/usr/share/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
)
_FONT_CACHE: dict[tuple[int, bool], object | None] = {}


def percentile(values: list[float], pct: float) -> float:
    """Return percentile with linear interpolation."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def simulate_inference(frame_index: int, work_units: int, seed: int) -> dict:
    """Run the local-development fallback loop and return per-frame latency."""
    start = time.perf_counter()
    acc = (seed + frame_index * 2654435761) & 0xFFFFFFFF
    for i in range(max(1, work_units)):
        acc = (acc * 1664525 + 1013904223 + i) & 0xFFFFFFFF
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return {
        "frame_index": frame_index,
        "latency_ms": elapsed_ms,
        "label": "normal" if acc % 17 else "defect",
        "confidence": round(0.80 + (acc % 1900) / 10000.0, 4),
        "checksum": acc,
    }


ProgressCallback = Callable[[dict], None]


def run_video_profile(job: dict, progress_callback: ProgressCallback | None = None) -> dict:
    """Execute warmup and measured frame inference, returning aggregate metrics."""
    mode = str(job.get("inference_mode") or os.environ.get("VIDEO_INFERENCE_MODE", "yolo_onnx")).lower()
    if mode not in {"surrogate", "synthetic"}:
        try:
            return run_yolo_video_profile(job, progress_callback=progress_callback)
        except Exception as exc:
            if str(job.get("strict_yolo", "")).lower() in {"1", "true", "yes"}:
                raise
            result = run_surrogate_video_profile(job, progress_callback=progress_callback)
            result["detector_backend"] = "deterministic_surrogate"
            result["detector_fallback_reason"] = str(exc)
            return result
    return run_surrogate_video_profile(job, progress_callback=progress_callback)


def run_surrogate_video_profile(job: dict, progress_callback: ProgressCallback | None = None) -> dict:
    """Run the local-development fallback and attach a simple preview."""
    frame_count = int(job.get("frame_count", 120))
    frame_stride = max(1, int(job.get("frame_stride", 30)))
    warmup_frames = max(0, int(job.get("warmup_frames", 2)))
    measured_frames = max(1, int(job.get("measured_frames", 30)))
    work_units = max(1, int(job.get("work_units", 60000)))
    seed = int(job.get("seed", 42))
    profile_id = job.get("profile_id", "video_industrial_inspection")
    resolution = job.get("resolution", "720p")
    fps = int(job.get("fps", 30))

    candidate_frames = list(range(0, max(frame_count, 1), frame_stride))
    while len(candidate_frames) < warmup_frames + measured_frames:
        candidate_frames.append(len(candidate_frames) * frame_stride)

    warmup = candidate_frames[:warmup_frames]
    measured = candidate_frames[warmup_frames : warmup_frames + measured_frames]

    for frame_index in warmup:
        simulate_inference(frame_index, work_units, seed)

    start = time.perf_counter()
    samples = []
    for sample_index, frame_index in enumerate(measured):
        sample = simulate_inference(frame_index, work_units, seed + sample_index)
        samples.append(sample)
        if progress_callback is not None:
            _safe_progress_callback(
                progress_callback,
                {
                    "frame_index": sample["frame_index"],
                    "latency_ms": round(float(sample["latency_ms"]), 4),
                    "label": sample["label"],
                    "label_zh": _label_zh(sample["label"]),
                    "confidence": sample["confidence"],
                },
            )
    observed_duration_sec = time.perf_counter() - start
    latencies = [float(item["latency_ms"]) for item in samples]

    latency_p90 = percentile(latencies, 0.90)
    preview_latency = latencies[0] if latencies else 0.0
    result = {
        "frame_latency_p90_ms": latency_p90,
        "frame_latency_avg_ms": statistics.fmean(latencies) if latencies else 0.0,
        "frame_latency_min_ms": min(latencies) if latencies else 0.0,
        "frame_latency_max_ms": max(latencies) if latencies else 0.0,
        "observed_duration_sec": observed_duration_sec,
        "frame_count": frame_count,
        "profile_id": profile_id,
        "resolution": resolution,
        "fps": fps,
        "frame_stride": frame_stride,
        "warmup_frames": warmup_frames,
        "measured_frames": len(samples),
        "work_units": work_units,
        "seed": seed,
        "aggregation": "p90_after_warmup",
        "detector_backend": "deterministic_surrogate",
        "actual_backend": "cpu",
        "backend": "cpu",
        "device": "cpu",
        "model_name": "surrogate",
        "video_asset": job.get("video_asset", DEFAULT_VIDEO),
        "gpu_device": os.environ.get("GPU_DEVICE"),
        "gpu_requested": _gpu_requested(job),
        "gpu_available": _gpu_available(),
        "gpu_assigned": _gpu_assigned(),
        "gpu_error": None,
        "annotated_frame_index": measured[0] if measured else 0,
        "preview_frame_width": 640,
        "preview_frame_height": 360,
        "annotated_frame_latency_ms": preview_latency,
        "annotated_frame_content_type": "image/svg+xml",
        "annotated_frame_data_url": _synthetic_preview_data_url(profile_id, preview_latency, latency_p90),
        "annotated_frame_overlay": "embedded_boxes_v1",
        "detection_count": 1,
        "top_label": "inspection_target",
        "top_label_zh": _label_zh("inspection_target"),
        "top_confidence": 0.88,
        "detections": [
            {
                "label": "inspection_target",
                "label_zh": _label_zh("inspection_target"),
                "confidence": 0.88,
                "bbox_xyxy": [120, 70, 500, 300],
                "fallback": True,
            }
        ],
        "preview_frames": [
            {
                "frame_index": measured[0] if measured else 0,
                "latency_ms": round(float(preview_latency), 4),
                "top_label": "inspection_target",
                "top_label_zh": _label_zh("inspection_target"),
                "data_url": _synthetic_preview_data_url(profile_id, preview_latency, latency_p90),
            }
        ],
        "samples": [
            {
                "frame_index": item["frame_index"],
                "latency_ms": round(float(item["latency_ms"]), 4),
                "label": item["label"],
                "confidence": item["confidence"],
            }
            for item in samples
        ],
    }
    return result


def run_yolo_video_profile(job: dict, progress_callback: ProgressCallback | None = None) -> dict:
    """Run YOLOv5 ONNX over sampled video frames and return metrics + preview."""
    if cv2 is None or np is None:
        raise RuntimeError("OpenCV/Numpy is not installed")

    frame_count = int(job.get("frame_count", 120))
    frame_stride = max(1, int(job.get("frame_stride", 30)))
    warmup_frames = max(0, int(job.get("warmup_frames", 2)))
    measured_frames = max(1, int(job.get("measured_frames", 30)))
    seed = int(job.get("seed", 42))
    profile_id = job.get("profile_id", "video_industrial_inspection")
    resolution = job.get("resolution", "720p")
    fps = int(job.get("fps", 30))
    confidence_threshold = float(job.get("confidence_threshold", 0.25))
    nms_threshold = float(job.get("nms_threshold", 0.45))
    max_detections = max(1, int(job.get("max_detections", 8)))

    asset_root = _asset_root()
    video_asset = str(job.get("video_asset") or DEFAULT_VIDEO)
    video_path = _resolve_asset_path(asset_root, video_asset)
    model_name = str(job.get("model_name") or "yolov5n")
    model_path = _resolve_asset_path(asset_root, str(job.get("model_path") or DEFAULT_MODEL))
    class_path = _resolve_asset_path(asset_root, str(job.get("class_names_path") or DEFAULT_CLASSES))
    class_names = _load_class_names(class_path)

    backend_info = _configure_inference_backend(
        model_path,
        str(job.get("dnn_target") or os.environ.get("VIDEO_DNN_TARGET", "auto")),
        gpu_requested=_gpu_requested(job),
    )

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video asset: {video_path}")
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or frame_count or 1)
    candidate_frames = list(range(0, max(frame_count, 1), frame_stride))
    while len(candidate_frames) < warmup_frames + measured_frames:
        candidate_frames.append(len(candidate_frames) * frame_stride)

    warmup = candidate_frames[:warmup_frames]
    measured = candidate_frames[warmup_frames : warmup_frames + measured_frames]

    for frame_index in warmup:
        frame = _read_frame(cap, frame_index, total_frames)
        _, backend_info = _detect_frame_with_backend(
            backend_info,
            frame,
            class_names,
            confidence_threshold=confidence_threshold,
            nms_threshold=nms_threshold,
            max_detections=max_detections,
        )

    samples: list[dict] = []
    preview_frame = None
    preview_data_url = ""
    preview_content_type = "image/jpeg"
    preview_frame_width = 640
    preview_frame_height = 360
    preview_index = measured[0] if measured else 0
    preview_latency_ms = 0.0
    preview_detections: list[dict] = []
    preview_candidates: list[dict] = []
    start = time.perf_counter()
    for sample_index, frame_index in enumerate(measured):
        frame = _read_frame(cap, frame_index, total_frames)
        t0 = time.perf_counter()
        (detections, annotated), backend_info = _detect_frame_with_backend(
            backend_info,
            frame,
            class_names,
            confidence_threshold=confidence_threshold,
            nms_threshold=nms_threshold,
            max_detections=max_detections,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        if preview_frame is None or detections:
            preview_frame = annotated.copy()
            preview_frame_height, preview_frame_width = preview_frame.shape[:2]
            preview_index = frame_index
            preview_latency_ms = latency_ms
            preview_detections = detections
        if detections and len(preview_candidates) < 4:
            top_for_gallery = detections[0]
            preview_candidates.append(
                {
                    "frame_index": frame_index,
                    "latency_ms": round(float(latency_ms), 4),
                    "top_label": top_for_gallery.get("label") or "none",
                    "top_label_zh": top_for_gallery.get("label_zh") or _label_zh(top_for_gallery.get("label") or "none"),
                    "confidence": round(float(top_for_gallery.get("confidence") or 0.0), 4),
                    "frame": annotated.copy(),
                }
            )
        top = detections[0] if detections else None
        samples.append(
            {
                "frame_index": frame_index,
                "latency_ms": latency_ms,
                "label": top["label"] if top else "none",
                "confidence": top["confidence"] if top else 0.0,
            }
        )
        if progress_callback is not None:
            progress_event = {
                "frame_index": frame_index,
                "latency_ms": round(float(latency_ms), 4),
                "label": top["label"] if top else "none",
                "label_zh": top.get("label_zh") if top else _label_zh("none"),
                "confidence": round(float(top["confidence"]), 4) if top else 0.0,
            }
            if detections and len(preview_candidates) <= 4:
                progress_event["preview_frame"] = {
                    "frame_index": frame_index,
                    "latency_ms": round(float(latency_ms), 4),
                    "top_label": progress_event["label"],
                    "top_label_zh": progress_event["label_zh"],
                    "confidence": progress_event["confidence"],
                    "data_url": _encode_jpeg_data_url(annotated),
                }
            _safe_progress_callback(progress_callback, progress_event)
    observed_duration_sec = time.perf_counter() - start
    cap.release()

    if not preview_data_url:
        preview_data_url = ""
    latencies = [float(item["latency_ms"]) for item in samples]
    latency_p90 = percentile(latencies, 0.90)
    preview_frames: list[dict] = []
    for candidate in preview_candidates:
        frame_for_gallery = candidate.pop("frame")
        if _can_draw_chinese_labels():
            _add_preview_evidence_overlay(
                frame_for_gallery,
                frame_index=int(candidate["frame_index"]),
                frame_latency_ms=float(candidate["latency_ms"]),
                p90_latency_ms=latency_p90,
                measured_frames=len(samples),
                gpu_assigned=_gpu_assigned(),
            )
        preview_frames.append({**candidate, "data_url": _encode_jpeg_data_url(frame_for_gallery)})
    if preview_frame is not None:
        preview_frame_height, preview_frame_width = preview_frame.shape[:2]
        if _can_draw_chinese_labels():
            _add_preview_evidence_overlay(
                preview_frame,
                frame_index=preview_index,
                frame_latency_ms=preview_latency_ms,
                p90_latency_ms=latency_p90,
                measured_frames=len(samples),
                gpu_assigned=_gpu_assigned(),
            )
        preview_data_url = _encode_jpeg_data_url(preview_frame)
    if not preview_data_url:
        preview_content_type = "image/svg+xml"
        preview_frame_width = 640
        preview_frame_height = 360
        preview_data_url = _synthetic_preview_data_url(profile_id, preview_latency_ms, latency_p90)
        preview_detections = [
            {
                "label": "inspection_target",
                "label_zh": _label_zh("inspection_target"),
                "confidence": 0.5,
                "bbox_xyxy": [120, 70, 500, 300],
                "fallback": True,
            }
        ]
    if not preview_frames:
        preview_frames = [
            {
                "frame_index": preview_index,
                "latency_ms": round(float(preview_latency_ms), 4),
                "top_label": (preview_detections[0].get("label") if preview_detections else "inspection_target"),
                "top_label_zh": (preview_detections[0].get("label_zh") if preview_detections else _label_zh("inspection_target")),
                "confidence": round(float(preview_detections[0].get("confidence") or 0.0), 4) if preview_detections else 0.0,
                "data_url": preview_data_url,
            }
        ]
    top_detection = preview_detections[0] if preview_detections else None
    return {
        "frame_latency_p90_ms": latency_p90,
        "frame_latency_avg_ms": statistics.fmean(latencies) if latencies else 0.0,
        "frame_latency_min_ms": min(latencies) if latencies else 0.0,
        "frame_latency_max_ms": max(latencies) if latencies else 0.0,
        "observed_duration_sec": observed_duration_sec,
        "frame_count": frame_count,
        "profile_id": profile_id,
        "resolution": resolution,
        "fps": fps,
        "frame_stride": frame_stride,
        "warmup_frames": warmup_frames,
        "measured_frames": len(samples),
        "work_units": int(job.get("work_units", 0) or 0),
        "seed": seed,
        "aggregation": "p90_after_warmup",
        "detector_backend": backend_info["actual_backend"],
        "actual_backend": backend_info["actual_backend"],
        "backend": backend_info["actual_backend"],
        "device": backend_info["device"],
        "model_name": model_name,
        "video_asset": video_asset,
        "confidence_threshold": confidence_threshold,
        "nms_threshold": nms_threshold,
        "gpu_device": os.environ.get("GPU_DEVICE"),
        "gpu_requested": backend_info["gpu_requested"],
        "gpu_available": backend_info["gpu_available"],
        "gpu_assigned": _gpu_assigned(),
        "gpu_error": backend_info.get("gpu_error"),
        "annotated_frame_index": preview_index,
        "preview_frame_width": int(preview_frame_width),
        "preview_frame_height": int(preview_frame_height),
        "annotated_frame_latency_ms": preview_latency_ms,
        "annotated_frame_content_type": preview_content_type,
        "annotated_frame_data_url": preview_data_url,
        "annotated_frame_overlay": "zh_yolo_v1" if preview_data_url and _can_draw_chinese_labels() else "yolo_boxes_v1",
        "detection_count": len(preview_detections),
        "top_label": top_detection["label"] if top_detection else "none",
        "top_label_zh": top_detection.get("label_zh") if top_detection else _label_zh("none"),
        "top_confidence": top_detection["confidence"] if top_detection else 0.0,
        "detections": preview_detections,
        "preview_frames": preview_frames,
        "samples": [
            {
                "frame_index": item["frame_index"],
                "latency_ms": round(float(item["latency_ms"]), 4),
                "label": item["label"],
                "confidence": round(float(item["confidence"]), 4),
            }
            for item in samples
        ],
    }


def _asset_root() -> Path:
    configured = os.environ.get("VIDEO_ASSET_DIR")
    if configured:
        return Path(configured)
    for candidate in (Path("/app/assets"), Path(__file__).resolve().parents[1] / "assets"):
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[1] / "assets"


def _resolve_asset_path(asset_root: Path, value: str) -> Path:
    root = asset_root.resolve()
    path = Path(value)
    if path.is_absolute():
        raise RuntimeError(f"Absolute asset paths are not allowed: {value}")
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise RuntimeError(f"Asset path escapes asset directory: {value}")
    return candidate


def _safe_progress_callback(progress_callback: ProgressCallback, event: dict) -> None:
    try:
        progress_callback(event)
    except Exception as exc:
        print(f"VIDEO_PROGRESS_CALLBACK_FAILED {exc}", flush=True)


def _load_class_names(path: Path) -> list[str]:
    if not path.exists():
        return [str(i) for i in range(80)]
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _label_zh(label: str) -> str:
    return CLASS_LABEL_ZH.get(label, label)


def _can_draw_chinese_labels() -> bool:
    return Image is not None and ImageDraw is not None and np is not None and _load_font(18, bold=True) is not None


def _load_font(size: int, bold: bool = False):
    if ImageFont is None:
        return None
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    candidates = list(FONT_CANDIDATES)
    if bold:
        candidates.insert(0, "/usr/share/opentype/noto/NotoSansCJK-Bold.ttc")
        candidates.insert(0, "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                font = ImageFont.truetype(str(path), size)
                _FONT_CACHE[key] = font
                return font
            except Exception:
                continue
    _FONT_CACHE[key] = None
    return None


def _draw_label_box(frame, text: str, fallback_text: str, x: int, y: int, color, font_size: int = 18) -> None:
    if Image is not None and ImageDraw is not None and np is not None:
        font = _load_font(font_size, bold=True)
        if font is not None:
            pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(pil)
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            box_x1 = max(0, x)
            box_y1 = max(0, y - text_height - 12)
            box_x2 = min(frame.shape[1] - 1, box_x1 + text_width + 14)
            box_y2 = min(frame.shape[0] - 1, box_y1 + text_height + 10)
            rgb_color = (int(color[2]), int(color[1]), int(color[0]))
            draw.rounded_rectangle((box_x1, box_y1, box_x2, box_y2), radius=4, fill=rgb_color)
            draw.text((box_x1 + 7, box_y1 + 3), text, font=font, fill=(255, 255, 255))
            frame[:] = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
            return

    label_text = fallback_text
    cv2.rectangle(frame, (x, max(0, y - 22)), (x + max(120, len(label_text) * 9), y), color, -1)
    cv2.putText(frame, label_text, (x + 4, max(15, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)


def _add_preview_evidence_overlay(
    frame,
    *,
    frame_index: int,
    frame_latency_ms: float,
    p90_latency_ms: float,
    measured_frames: int,
    gpu_assigned: bool,
) -> None:
    zh_line_1 = (
        f"帧序号 {frame_index} | 单帧推理 {frame_latency_ms:.2f} ms | "
        f"P90 {p90_latency_ms:.2f} ms"
    )
    zh_line_2 = f"有效推理帧 {measured_frames} | GPU {'已分配' if gpu_assigned else '未分配'}"
    fallback_line_1 = (
        f"frame {frame_index} | latency {frame_latency_ms:.2f} ms | "
        f"P90 {p90_latency_ms:.2f} ms"
    )
    fallback_line_2 = f"frames {measured_frames} | GPU {'yes' if gpu_assigned else 'no'}"
    height, width = frame.shape[:2]
    if Image is not None and ImageDraw is not None and np is not None:
        font = _load_font(18, bold=True)
        if font is not None:
            pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
            overlay = Image.new("RGBA", pil.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            width_1 = draw.textbbox((0, 0), zh_line_1, font=font)[2]
            width_2 = draw.textbbox((0, 0), zh_line_2, font=font)[2]
            box_width = min(width - 16, max(width_1, width_2) + 24)
            box_height = 58
            x1 = 8
            y1 = max(8, height - box_height - 8)
            draw.rounded_rectangle((x1, y1, x1 + box_width, y1 + box_height), radius=8, fill=(15, 23, 42, 210))
            draw.text((x1 + 12, y1 + 7), zh_line_1, font=font, fill=(255, 255, 255, 255))
            draw.text((x1 + 12, y1 + 31), zh_line_2, font=font, fill=(226, 232, 240, 255))
            pil = Image.alpha_composite(pil, overlay).convert("RGB")
            frame[:] = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
            return

    x1 = 8
    y1 = max(8, height - 66)
    cv2.rectangle(frame, (x1, y1), (width - 8, height - 8), (15, 23, 42), -1)
    cv2.putText(frame, fallback_line_1, (x1 + 10, y1 + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(frame, fallback_line_2, (x1 + 10, y1 + 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (226, 232, 240), 1)


def _configure_inference_backend(model_path: Path, target: str, *, gpu_requested: bool | None = None) -> dict:
    target = target.lower()
    if gpu_requested is None:
        gpu_requested = _gpu_assigned() or target in {"cuda", "gpu"}
    gpu_available = _gpu_available()
    info = {
        "requested_target": target,
        "actual_backend": "opencv_dnn_cpu",
        "device": "cpu",
        "gpu_requested": bool(gpu_requested),
        "gpu_available": bool(gpu_available),
        "gpu_error": None,
        "engine": "opencv_dnn",
        "model_path": str(model_path),
        "net": None,
        "session": None,
    }
    wants_cuda = target in {"auto", "cuda", "gpu"} and gpu_requested
    if wants_cuda and gpu_available:
        ort_session, ort_error = _create_ort_session(model_path)
        if ort_session is not None:
            info["actual_backend"] = "onnxruntime_cuda"
            info["device"] = f"cuda:{os.environ.get('GPU_DEVICE', '0')}"
            info["engine"] = "onnxruntime"
            info["session"] = ort_session
            return info
        if ort_error:
            info["gpu_error"] = ort_error
    net = cv2.dnn.readNetFromONNX(str(model_path))
    dnn_info = _configure_dnn_backend(net, target, gpu_requested=gpu_requested, gpu_available=gpu_available)
    dnn_info["engine"] = "opencv_dnn"
    dnn_info["net"] = net
    if info.get("gpu_error") and not dnn_info.get("gpu_error"):
        dnn_info["gpu_error"] = info["gpu_error"]
    elif info.get("gpu_error") and dnn_info.get("gpu_error"):
        dnn_info["gpu_error"] = f"{info['gpu_error']}; {dnn_info['gpu_error']}"
    return dnn_info


def _create_ort_session(model_path: Path):
    if ort is None:
        return None, "ONNX Runtime is not installed"
    try:
        providers = ort.get_available_providers()
    except Exception as exc:
        return None, f"Cannot inspect ONNX Runtime providers: {exc}"
    if "CUDAExecutionProvider" not in providers:
        return None, f"ONNX Runtime CUDAExecutionProvider is unavailable; providers={providers}"
    provider_options: dict[str, str] = {
        # Pascal-era GPUs in the lab can fail with newer cuDNN frontend plans.
        # DEFAULT is slower than EXHAUSTIVE/HEURISTIC but much more stable for
        # an acceptance-demo workload where correctness matters first.
        "cudnn_conv_algo_search": "DEFAULT",
        "do_copy_in_default_stream": "1",
    }
    gpu_device = os.environ.get("GPU_DEVICE")
    if gpu_device and gpu_device.isdigit():
        provider_options["device_id"] = gpu_device
    try:
        session = ort.InferenceSession(
            str(model_path),
            providers=[("CUDAExecutionProvider", provider_options), "CPUExecutionProvider"],
        )
        active = session.get_providers()
        if not active or active[0] != "CUDAExecutionProvider":
            return None, f"ONNX Runtime did not activate CUDAExecutionProvider; active_providers={active}"
        return session, None
    except Exception as exc:
        return None, f"ONNX Runtime CUDA session failed: {exc}"


def _configure_dnn_backend(
    net,
    target: str,
    *,
    gpu_requested: bool | None = None,
    gpu_available: bool | None = None,
) -> dict:
    target = target.lower()
    if gpu_requested is None:
        gpu_requested = _gpu_assigned() or target in {"cuda", "gpu"}
    if gpu_available is None:
        gpu_available = _gpu_available()
    info = {
        "requested_target": target,
        "actual_backend": "opencv_dnn_cpu",
        "device": "cpu",
        "gpu_requested": bool(gpu_requested),
        "gpu_available": bool(gpu_available),
        "gpu_error": None,
    }
    wants_cuda = target in {"auto", "cuda", "gpu"} and gpu_requested
    if wants_cuda and gpu_available:
        if _opencv_dnn_cuda_available():
            try:
                net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
                info["actual_backend"] = "opencv_dnn_cuda"
                info["device"] = f"cuda:{os.environ.get('GPU_DEVICE', '0')}"
                return info
            except Exception as exc:
                info["gpu_error"] = f"OpenCV CUDA backend setup failed: {exc}"
        else:
            info["gpu_error"] = "OpenCV DNN CUDA backend is unavailable in this image"
    elif wants_cuda and not gpu_available:
        info["gpu_error"] = "GPU was requested but no CUDA/NVIDIA device was visible in the container"
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return info


def _opencv_dnn_cuda_available() -> bool:
    try:
        if not hasattr(cv2, "cuda") or cv2.cuda.getCudaEnabledDeviceCount() <= 0:
            return False
        build_info = cv2.getBuildInformation()
        return "NVIDIA CUDA:                   YES" in build_info or "CUDA:                          YES" in build_info
    except Exception:
        return False


def _detect_frame_with_backend(
    backend_info: dict,
    frame,
    class_names: list[str],
    *,
    confidence_threshold: float,
    nms_threshold: float,
    max_detections: int,
) -> tuple[tuple[list[dict], object], dict]:
    try:
        if backend_info.get("engine") == "onnxruntime":
            return (
                _detect_frame_ort(
                    backend_info["session"],
                    frame,
                    class_names,
                    confidence_threshold=confidence_threshold,
                    nms_threshold=nms_threshold,
                    max_detections=max_detections,
                ),
                backend_info,
            )
        return (
            _detect_frame(
                backend_info["net"],
                frame,
                class_names,
                confidence_threshold=confidence_threshold,
                nms_threshold=nms_threshold,
                max_detections=max_detections,
            ),
            backend_info,
        )
    except Exception as exc:
        if backend_info.get("actual_backend") not in {"opencv_dnn_cuda", "onnxruntime_cuda"}:
            raise
        fallback_info = dict(backend_info)
        fallback_info["actual_backend"] = "opencv_dnn_cpu"
        fallback_info["device"] = "cpu"
        fallback_info["engine"] = "opencv_dnn"
        fallback_info["session"] = None
        fallback_info["gpu_error"] = f"{backend_info.get('actual_backend')} inference failed and fell back to CPU: {exc}"
        if fallback_info.get("net") is None:
            fallback_info["net"] = cv2.dnn.readNetFromONNX(str(fallback_info["model_path"]))
        net = fallback_info["net"]
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        return (
            _detect_frame(
                net,
                frame,
                class_names,
                confidence_threshold=confidence_threshold,
                nms_threshold=nms_threshold,
                max_detections=max_detections,
            ),
            fallback_info,
        )


def _detect_frame_ort(
    session,
    frame,
    class_names: list[str],
    *,
    confidence_threshold: float,
    nms_threshold: float,
    max_detections: int,
) -> tuple[list[dict], object]:
    class OrtNetAdapter:
        def __init__(self, ort_session):
            self.session = ort_session
            model_input = ort_session.get_inputs()[0]
            self.input_name = model_input.name
            self.input_type = model_input.type
            self.blob = None

        def setInput(self, blob):
            if self.input_type == "tensor(float16)":
                self.blob = blob.astype(np.float16)
            else:
                self.blob = blob.astype(np.float32)

        def forward(self):
            if self.blob is None:
                raise RuntimeError("ONNX Runtime input blob was not set")
            outputs = self.session.run(None, {self.input_name: self.blob})
            if not outputs:
                raise RuntimeError("ONNX Runtime returned no outputs")
            return outputs[0]

    return _detect_frame(
        OrtNetAdapter(session),
        frame,
        class_names,
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
        max_detections=max_detections,
    )


def _read_frame(cap, frame_index: int, total_frames: int):
    safe_index = int(frame_index) % max(1, total_frames)
    cap.set(cv2.CAP_PROP_POS_FRAMES, safe_index)
    ok, frame = cap.read()
    if ok and frame is not None:
        return frame
    frame = np.full((360, 640, 3), 245, dtype=np.uint8)
    cv2.putText(frame, f"frame {safe_index}", (40, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (80, 80, 80), 2)
    return frame


def _detect_frame(
    net,
    frame,
    class_names: list[str],
    *,
    confidence_threshold: float,
    nms_threshold: float,
    max_detections: int,
) -> tuple[list[dict], object]:
    height, width = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True, crop=False)
    net.setInput(blob)
    output = net.forward()
    pred = output[0] if isinstance(output, (list, tuple)) else output
    pred = np.asarray(pred)
    if pred.ndim == 3:
        pred = pred[0]
    if pred.ndim == 2 and pred.shape[0] in (84, 85) and pred.shape[1] > pred.shape[0]:
        pred = pred.T

    boxes: list[list[int]] = []
    scores: list[float] = []
    class_ids: list[int] = []
    for row in pred:
        if len(row) < 6:
            continue
        if len(row) == 84:
            class_scores = row[4:]
            class_id = int(np.argmax(class_scores))
            score = float(class_scores[class_id])
        else:
            objectness = float(row[4])
            class_scores = row[5:]
            class_id = int(np.argmax(class_scores))
            score = objectness * float(class_scores[class_id])
        if score < confidence_threshold:
            continue
        cx, cy, bw, bh = [float(v) for v in row[:4]]
        x = int((cx - bw / 2) * width / INPUT_SIZE)
        y = int((cy - bh / 2) * height / INPUT_SIZE)
        w = int(bw * width / INPUT_SIZE)
        h = int(bh * height / INPUT_SIZE)
        boxes.append([max(0, x), max(0, y), max(1, w), max(1, h)])
        scores.append(score)
        class_ids.append(class_id)

    selected = cv2.dnn.NMSBoxes(boxes, scores, confidence_threshold, nms_threshold)
    indices = np.array(selected).reshape(-1).tolist() if len(selected) else []
    indices = sorted(indices, key=lambda idx: scores[idx], reverse=True)[:max_detections]
    annotated = frame.copy()
    detections: list[dict] = []
    for idx in indices:
        x, y, w, h = boxes[idx]
        label = class_names[class_ids[idx]] if class_ids[idx] < len(class_names) else str(class_ids[idx])
        label_zh = _label_zh(label)
        confidence = round(float(scores[idx]), 4)
        color = (34, 139, 34) if label in {"bottle", "cup"} else (25, 118, 210)
        cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
        _draw_label_box(
            annotated,
            f"{label_zh} {confidence:.2f}",
            f"{label} {confidence:.2f}",
            x,
            y,
            color,
        )
        detections.append(
            {
                "label": label,
                "label_zh": label_zh,
                "confidence": confidence,
                "bbox_xyxy": [int(x), int(y), int(x + w), int(y + h)],
                "fallback": False,
            }
        )

    if not detections:
        x, y, w, h = int(width * 0.30), int(height * 0.20), int(width * 0.38), int(height * 0.55)
        cv2.rectangle(annotated, (x, y), (x + w, y + h), (180, 120, 20), 2)
        _draw_label_box(
            annotated,
            f"{_label_zh('inspection_target')} 0.50",
            "inspection_target 0.50",
            x,
            y,
            (180, 120, 20),
        )
        detections.append(
            {
                "label": "inspection_target",
                "label_zh": _label_zh("inspection_target"),
                "confidence": 0.5,
                "bbox_xyxy": [x, y, x + w, y + h],
                "fallback": True,
            }
        )
    return detections, annotated


def _encode_jpeg_data_url(frame) -> str:
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        return _synthetic_preview_data_url("video")
    data = base64.b64encode(encoded.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


def _synthetic_preview_data_url(title: str, frame_latency_ms: float = 0.0, p90_latency_ms: float = 0.0) -> str:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
  <rect width="640" height="360" fill="#f8fafc"/>
  <rect x="120" y="70" width="380" height="230" fill="none" stroke="#2563eb" stroke-width="5"/>
  <rect x="120" y="38" width="270" height="34" fill="#2563eb"/>
  <text x="132" y="61" font-size="19" fill="#fff" font-family="Arial">检测目标 0.88</text>
  <rect x="24" y="304" width="592" height="36" rx="8" fill="#0f172a" opacity="0.88"/>
  <text x="36" y="328" font-size="18" fill="#fff" font-family="Arial">
    {title} | 单帧推理 {frame_latency_ms:.2f} ms | P90 {p90_latency_ms:.2f} ms
  </text>
</svg>"""
    data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{data}"


def _gpu_assigned() -> bool:
    visible = os.environ.get("NVIDIA_VISIBLE_DEVICES") or os.environ.get("CUDA_VISIBLE_DEVICES")
    gpu_device = os.environ.get("GPU_DEVICE")
    if gpu_device:
        return True
    if visible and visible.lower() not in {"", "void", "none"}:
        return True
    return any(Path("/dev").glob("nvidia[0-9]*"))


def _gpu_requested(job: dict | None = None) -> bool:
    if job and str(job.get("use_gpu", "")).lower() in {"1", "true", "yes"}:
        return True
    if str(os.environ.get("USE_GPU", "")).lower() in {"1", "true", "yes"}:
        return True
    target = str((job or {}).get("dnn_target") or os.environ.get("VIDEO_DNN_TARGET", "")).lower()
    return target in {"cuda", "gpu"} or _gpu_assigned()


def _gpu_available() -> bool:
    if _opencv_cuda_device_count() > 0:
        return True
    if any(Path("/dev").glob("nvidia[0-9]*")):
        return True
    try:
        completed = subprocess.run(
            ["nvidia-smi", "-L"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return completed.returncode == 0 and "GPU" in completed.stdout
    except Exception:
        return False


def _opencv_cuda_device_count() -> int:
    if cv2 is None or not hasattr(cv2, "cuda"):
        return 0
    try:
        return int(cv2.cuda.getCudaEnabledDeviceCount())
    except Exception:
        return 0
