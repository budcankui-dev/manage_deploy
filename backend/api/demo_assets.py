"""Read-only demo assets for evidence previews in task/order details."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from config import settings

router = APIRouter(prefix="/api/demo-assets", tags=["demo-assets"])

REPO_ROOT = Path(__file__).resolve().parents[2]
VIDEO_ASSET_DIR = REPO_ROOT / "workers" / "low-latency-video" / "assets"
METAVERSE_VIDEO_ASSET_DIR = REPO_ROOT / "workers" / "metaverse-video-fusion" / "assets" / "videos"
ALLOWED_VIDEO_ASSETS = {
    "bottle-detection.mp4": "video/mp4",
    "cam0.mp4": "video/mp4",
    "cam1.mp4": "video/mp4",
}
INSTANCE_ID_PATTERN = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def _metaverse_result_key(instance_id: str, asset_name: str) -> str:
    if not INSTANCE_ID_PATTERN.match(instance_id):
        raise HTTPException(status_code=400, detail="Invalid instance id")
    if asset_name not in {"fusion-result.mp4", "fusion-preview.jpg", "result.json"}:
        raise HTTPException(status_code=404, detail="Metaverse result asset not found")
    return f"{instance_id}/metaverse/{asset_name}"


@router.get("/video/{asset_name}")
async def get_video_asset(asset_name: str):
    """Serve fixed acceptance-test videos by allow-listed file name."""
    media_type = ALLOWED_VIDEO_ASSETS.get(asset_name)
    if not media_type:
        raise HTTPException(status_code=404, detail="Demo video asset not found")

    asset_dir = METAVERSE_VIDEO_ASSET_DIR if asset_name in {"cam0.mp4", "cam1.mp4"} else VIDEO_ASSET_DIR
    path = (asset_dir / asset_name).resolve()
    if not path.is_file() or asset_dir.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="Demo video asset not found")

    return FileResponse(path, media_type=media_type, filename=asset_name)


@router.get("/metaverse-results/{instance_id}/{asset_name}")
async def get_metaverse_result_asset(instance_id: str, asset_name: str, request: Request):
    """Proxy a durable MinIO result object without exposing storage credentials."""
    if not settings.minio_access_key or not settings.minio_secret_key:
        raise HTTPException(status_code=503, detail="MinIO credentials are not configured")
    try:
        from minio import Minio

        client = Minio(
            settings.minio_endpoint.replace("http://", "").replace("https://", ""),
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_endpoint.startswith("https://"),
        )
        key = _metaverse_result_key(instance_id, asset_name)
        object_size = client.stat_object(settings.minio_bucket, key).size
        offset, length = 0, object_size
        status_code = 200
        headers = {"Accept-Ranges": "bytes", "Content-Length": str(object_size)}
        range_header = request.headers.get("range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match:
                raise HTTPException(status_code=416, detail="Invalid byte range")
            start_text, end_text = match.groups()
            if start_text:
                offset = int(start_text)
                end = int(end_text) if end_text else object_size - 1
            elif end_text:
                suffix = int(end_text)
                offset = max(object_size - suffix, 0)
                end = object_size - 1
            else:
                raise HTTPException(status_code=416, detail="Invalid byte range")
            if offset >= object_size or end < offset:
                raise HTTPException(status_code=416, detail="Requested range is not satisfiable")
            end = min(end, object_size - 1)
            length = end - offset + 1
            status_code = 206
            headers.update({
                "Content-Length": str(length),
                "Content-Range": f"bytes {offset}-{end}/{object_size}",
            })
        response = client.get_object(settings.minio_bucket, key, offset=offset, length=length)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Metaverse result asset unavailable: {exc}") from exc

    media_type = {"fusion-result.mp4": "video/mp4", "fusion-preview.jpg": "image/jpeg", "result.json": "application/json"}[asset_name]

    def stream():
        try:
            while chunk := response.read(1024 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(stream(), media_type=media_type, status_code=status_code, headers=headers)
