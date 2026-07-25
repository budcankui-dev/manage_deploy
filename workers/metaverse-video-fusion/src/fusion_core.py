"""Metaverse video fusion core.

This worker reuses the MODNet matting idea from ``metaverse_app`` but exposes it
as the same benchmark/runtime contract used by the low-latency video worker.
"""

from __future__ import annotations

import math
import os
import statistics
import subprocess
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None
    np = None

try:
    import torch  # type: ignore
    import torch.nn as nn  # type: ignore
    import torchvision.transforms as transforms  # type: ignore
except Exception:  # pragma: no cover
    torch = None
    nn = None
    transforms = None

try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover
    Image = None


DEFAULT_VIDEO0 = "cam0.mp4"
DEFAULT_VIDEO1 = "cam1.mp4"
DEFAULT_PROFILE = "metaverse_offline_fusion_720p"
DEFAULT_CKPT = "MODNet/pretrained/modnet_webcam_portrait_matting.ckpt"
_MODEL_CACHE: dict[tuple[str, str], Any] = {}


def percentile(values: list[float], pct: float) -> float:
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


def _asset_dir() -> Path:
    return Path(os.environ.get("METAVERSE_ASSET_DIR") or "/app/assets")


def _asset_path(value: str, *, default_subdir: str = "") -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    base = _asset_dir()
    if default_subdir and not value.startswith(default_subdir):
        return base / default_subdir / value
    return base / value


def _gpu_requested(job: dict[str, Any]) -> bool:
    raw = str(job.get("use_gpu") if "use_gpu" in job else os.environ.get("USE_GPU", "true"))
    return raw.lower() in {"1", "true", "yes", "on"}


def _gpu_assigned() -> bool:
    for key in ("GPU_DEVICE", "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"):
        value = os.environ.get(key)
        if value and value.lower() not in {"none", "void", "null", "-1"}:
            return True
    return False


def _gpu_available() -> bool:
    if torch is not None:
        try:
            return bool(torch.cuda.is_available())
        except Exception:
            pass
    try:
        return subprocess.run(
            ["nvidia-smi"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        ).returncode == 0
    except Exception:
        return False


def _device_for(job: dict[str, Any]) -> tuple[str, str | None]:
    if _gpu_requested(job):
        if torch is None:
            return "cpu", "torch is not installed"
        if torch.cuda.is_available():
            gpu = os.environ.get("GPU_DEVICE") or os.environ.get("CUDA_VISIBLE_DEVICES") or "0"
            return "cuda:0", None if _gpu_assigned() else "CUDA visible but GPU_DEVICE was not assigned"
        return "cpu", "CUDA is not available inside the container"
    return "cpu", None


def _load_modnet(device: str, ckpt_path: Path):
    if torch is None or nn is None or transforms is None or Image is None:
        raise RuntimeError("torch, torchvision and pillow are required for MODNet fusion")
    modnet_root = _asset_dir() / "MODNet"
    import sys

    if str(modnet_root) not in sys.path:
        sys.path.insert(0, str(modnet_root))
    from src.models.modnet import MODNet  # type: ignore

    cache_key = (device, str(ckpt_path))
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    model = MODNet(backbone_pretrained=False)
    if device.startswith("cuda"):
        model = nn.DataParallel(model).cuda()
        state = torch.load(ckpt_path, map_location="cuda")
    else:
        model = nn.DataParallel(model)
        state = torch.load(ckpt_path, map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    _MODEL_CACHE[cache_key] = model
    return model


def _transforms():
    return transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])


def _resize_for_modnet(height: int, width: int) -> tuple[int, int]:
    if width >= height:
        rh, rw = 512, int(width / height * 512)
    else:
        rw, rh = 512, int(height / width * 512)
    return max(32, rh - rh % 32), max(32, rw - rw % 32)


def _jpeg_bytes(frame_rgb, quality: int = 90) -> bytes:
    if cv2 is None:
        raise RuntimeError("opencv-python-headless is required to encode previews")
    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("failed to encode fusion preview")
    return buf.tobytes()


def _read_video_pairs(job: dict[str, Any]) -> list[tuple[int, Any, Any]]:
    if cv2 is None:
        raise RuntimeError("opencv-python-headless is required for video fusion")

    video0 = _asset_path(str(job.get("video0_asset") or DEFAULT_VIDEO0), default_subdir="videos")
    video1 = _asset_path(str(job.get("video1_asset") or DEFAULT_VIDEO1), default_subdir="videos")
    cap0 = cv2.VideoCapture(str(video0))
    cap1 = cv2.VideoCapture(str(video1))
    if not cap0.isOpened() or not cap1.isOpened():
        raise RuntimeError(f"failed to open input videos: {video0}, {video1}")

    frame_count = int(job.get("frame_count", 180) or 180)
    stride = max(1, int(job.get("frame_stride", 1) or 1))
    need = max(1, int(job.get("warmup_frames", 10) or 10) + int(job.get("measured_frames", 170) or 170))
    pairs = []
    index = 0
    while len(pairs) < need and index < frame_count:
        ok0, bgr0 = cap0.read()
        ok1, bgr1 = cap1.read()
        if not ok0 or not ok1:
            break
        if index % stride == 0:
            pairs.append((index, cv2.cvtColor(bgr0, cv2.COLOR_BGR2RGB), cv2.cvtColor(bgr1, cv2.COLOR_BGR2RGB)))
        index += 1
    cap0.release()
    cap1.release()
    if not pairs:
        raise RuntimeError("no input frame pairs were available for fusion")
    return pairs


def _fuse_pair(model, transform, device: str, fg_frame, bg_frame):
    if cv2 is None or np is None or torch is None or Image is None:
        raise RuntimeError("opencv, numpy, torch and pillow are required for fusion")
    height, width = fg_frame.shape[:2]
    rh, rw = _resize_for_modnet(height, width)
    bg_resized = cv2.resize(bg_frame, (width, height), cv2.INTER_AREA)
    fg_resized = cv2.resize(fg_frame, (rw, rh), cv2.INTER_AREA)
    tensor = transform(Image.fromarray(fg_resized)).unsqueeze(0)
    if device.startswith("cuda"):
        tensor = tensor.cuda()
    with torch.no_grad():
        _, _, matte_t = model(tensor, True)
    matte = np.squeeze(matte_t[0].detach().cpu().numpy().transpose(1, 2, 0), -1)
    matte = cv2.resize(matte, (width, height), cv2.INTER_LINEAR)
    if matte.max() > 0:
        matte = matte / matte.max()
    return (fg_frame * matte[..., np.newaxis] + bg_resized * (1 - matte[..., np.newaxis])).astype(np.uint8)


def run_fusion_profile(job: dict[str, Any]) -> dict[str, Any]:
    """Fuse sampled video frames and return benchmark-compatible metrics."""
    device, gpu_error = _device_for(job)
    strict_gpu = str(job.get("strict_gpu") or os.environ.get("STRICT_GPU", "true")).lower() in {"1", "true", "yes"}
    if strict_gpu and _gpu_requested(job) and not device.startswith("cuda"):
        raise RuntimeError(gpu_error or "GPU requested but CUDA is unavailable")

    ckpt = _asset_path(str(job.get("modnet_checkpoint") or DEFAULT_CKPT))
    pairs = _read_video_pairs(job)
    warmup_frames = max(0, int(job.get("warmup_frames", 10) or 10))
    measured_frames = max(1, int(job.get("measured_frames", 170) or 170))
    while len(pairs) < warmup_frames + measured_frames:
        pairs.append(pairs[len(pairs) % len(pairs)])
    warmup = pairs[:warmup_frames]
    measured = pairs[warmup_frames:warmup_frames + measured_frames]

    model = _load_modnet(device, ckpt)
    transform = _transforms()

    for _, frame0, frame1 in warmup:
        _fuse_pair(model, transform, device, frame0, frame1)
        if torch is not None and device.startswith("cuda"):
            torch.cuda.synchronize()

    samples = []
    preview_jpeg: bytes | None = None
    archive_path = Path(tempfile.mkstemp(prefix="metaverse-fusion-", suffix=".mp4")[1])
    video_writer = None
    start = time.perf_counter()
    for sample_index, (frame_index, frame0, frame1) in enumerate(measured):
        if torch is not None and device.startswith("cuda"):
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        fused = _fuse_pair(model, transform, device, frame0, frame1)
        if torch is not None and device.startswith("cuda"):
            torch.cuda.synchronize()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        samples.append({"frame_index": frame_index, "latency_ms": round(elapsed_ms, 4)})
        if video_writer is None:
            height, width = fused.shape[:2]
            video_writer = cv2.VideoWriter(
                str(archive_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                float(int(job.get("fps", 30) or 30)),
                (width, height),
            )
            if not video_writer.isOpened():
                raise RuntimeError("failed to create fusion MP4 archive")
        video_writer.write(cv2.cvtColor(fused, cv2.COLOR_RGB2BGR))
        if preview_jpeg is None:
            preview_jpeg = _jpeg_bytes(fused)
    if video_writer is not None:
        video_writer.release()
    observed_duration_sec = time.perf_counter() - start
    latencies = [float(item["latency_ms"]) for item in samples]
    p90 = percentile(latencies, 0.90)
    height = int(measured[0][1].shape[0]) if measured else 0
    width = int(measured[0][1].shape[1]) if measured else 0

    return {
        "frame_latency_p90_ms": p90,
        "frame_latency_avg_ms": statistics.fmean(latencies) if latencies else 0.0,
        "frame_latency_min_ms": min(latencies) if latencies else 0.0,
        "frame_latency_max_ms": max(latencies) if latencies else 0.0,
        "observed_duration_sec": observed_duration_sec,
        "profile_id": job.get("profile_id", DEFAULT_PROFILE),
        "resolution": job.get("resolution", "720p"),
        "fps": int(job.get("fps", 30) or 30),
        "frame_count": int(job.get("frame_count", 180) or 180),
        "frame_stride": max(1, int(job.get("frame_stride", 1) or 1)),
        "warmup_frames": warmup_frames,
        "measured_frames": len(samples),
        "aggregation": "p90_after_warmup",
        "fusion_mode": "modnet_offline",
        "model_name": "MODNet",
        "video0_asset": job.get("video0_asset", DEFAULT_VIDEO0),
        "video1_asset": job.get("video1_asset", DEFAULT_VIDEO1),
        "actual_backend": "torch_cuda" if device.startswith("cuda") else "torch_cpu",
        "backend": "torch_cuda" if device.startswith("cuda") else "torch_cpu",
        "detector_backend": "modnet_fusion",
        "device": device,
        "gpu_device": os.environ.get("GPU_DEVICE"),
        "gpu_requested": _gpu_requested(job),
        "gpu_available": _gpu_available(),
        "gpu_assigned": _gpu_assigned(),
        "gpu_error": gpu_error,
        "preview_frame_index": samples[0]["frame_index"] if samples else None,
        "preview_frame_width": width,
        "preview_frame_height": height,
        "fusion_archive_path": str(archive_path),
        "fusion_preview_jpeg": preview_jpeg or b"",
        "samples": samples,
    }
