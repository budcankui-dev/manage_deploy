"""Read-only demo assets for evidence previews in task/order details."""

from __future__ import annotations

import hmac
import json
import re
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse

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


def _metaverse_result_dir(instance_id: str) -> Path:
    if not INSTANCE_ID_PATTERN.match(instance_id):
        raise HTTPException(status_code=400, detail="Invalid instance id")
    return Path(settings.platform_scratch_root).resolve() / instance_id / "results"


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


@router.post("/metaverse-results/{instance_id}/frame-sequence")
async def upload_metaverse_frame_sequence(
    instance_id: str,
    request: Request,
    x_service_token: str | None = Header(default=None),
):
    """Persist sink-side fusion frames outside the metric row payload."""
    if settings.service_api_token and not hmac.compare_digest(x_service_token or "", settings.service_api_token):
        raise HTTPException(status_code=403, detail="Invalid service token")
    payload = await request.json()
    frames = payload.get("frames")
    if not isinstance(frames, list) or not frames:
        raise HTTPException(status_code=400, detail="frames must be a non-empty list")
    result_dir = _metaverse_result_dir(instance_id)
    result_dir.mkdir(parents=True, exist_ok=True)
    content = {"fps": int(payload.get("fps") or 30), "frame_count": len(frames), "frames": frames}
    (result_dir / "metaverse-fusion-frames.json").write_text(
        json.dumps(content, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return {
        "url": f"/api/demo-assets/metaverse-results/{instance_id}/frame-sequence",
        "frame_count": len(frames),
        "fps": content["fps"],
    }


@router.get("/metaverse-results/{instance_id}/frame-sequence")
async def get_metaverse_frame_sequence(instance_id: str):
    path = _metaverse_result_dir(instance_id) / "metaverse-fusion-frames.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Metaverse frame sequence not found")
    return FileResponse(path, media_type="application/json", filename="metaverse-fusion-frames.json")
