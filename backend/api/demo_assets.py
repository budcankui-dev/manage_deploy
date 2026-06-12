"""Read-only demo assets for evidence previews in task/order details."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/demo-assets", tags=["demo-assets"])

REPO_ROOT = Path(__file__).resolve().parents[2]
VIDEO_ASSET_DIR = REPO_ROOT / "workers" / "low-latency-video" / "assets"
ALLOWED_VIDEO_ASSETS = {
    "bottle-detection.mp4": "video/mp4",
}


@router.get("/video/{asset_name}")
async def get_video_asset(asset_name: str):
    """Serve fixed acceptance-test videos by allow-listed file name."""
    media_type = ALLOWED_VIDEO_ASSETS.get(asset_name)
    if not media_type:
        raise HTTPException(status_code=404, detail="Demo video asset not found")

    path = (VIDEO_ASSET_DIR / asset_name).resolve()
    if not path.is_file() or VIDEO_ASSET_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="Demo video asset not found")

    return FileResponse(path, media_type=media_type, filename=asset_name)
