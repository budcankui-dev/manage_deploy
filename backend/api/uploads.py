"""用户文件上传 API。

支持用户通过对话上传输入数据文件到 MinIO，并记录元数据到 user_uploaded_objects 表。
Worker 通过 INPUT_OBJECTS 环境变量获取输入对象列表。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from config import settings
from database import get_db
from models import UserUploadedObject, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    conversation_id: str | None = Query(None),
    order_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传文件到 MinIO 并记录元数据。"""
    content = await file.read()
    size_bytes = len(content)
    sha256 = hashlib.sha256(content).hexdigest()

    bucket = settings.minio_bucket or "task-inputs"
    object_key = f"user-{current_user.id}/{datetime.utcnow().strftime('%Y%m%d')}/{file.filename}"
    uri = f"s3://{bucket}/{object_key}"

    uploaded = await _upload_to_minio(bucket, object_key, content, file.content_type)
    if not uploaded:
        raise HTTPException(status_code=502, detail="Failed to upload to MinIO")

    obj = UserUploadedObject(
        user_id=current_user.id,
        conversation_id=conversation_id,
        order_id=order_id,
        bucket=bucket,
        object_key=object_key,
        uri=uri,
        filename=file.filename,
        content_type=file.content_type,
        size_bytes=size_bytes,
        sha256=sha256,
        status="uploaded",
    )
    db.add(obj)
    await db.flush()
    return {
        "id": obj.id,
        "uri": uri,
        "filename": file.filename,
        "size_bytes": size_bytes,
        "sha256": sha256,
    }


@router.get("")
async def list_uploads(
    conversation_id: str | None = Query(None),
    order_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户的上传文件。"""
    query = select(UserUploadedObject).where(UserUploadedObject.user_id == current_user.id)
    if conversation_id:
        query = query.where(UserUploadedObject.conversation_id == conversation_id)
    if order_id:
        query = query.where(UserUploadedObject.order_id == order_id)
    query = query.order_by(UserUploadedObject.created_at.desc())
    result = await db.execute(query)
    objects = result.scalars().all()
    return [
        {
            "id": obj.id,
            "uri": obj.uri,
            "filename": obj.filename,
            "content_type": obj.content_type,
            "size_bytes": obj.size_bytes,
            "sha256": obj.sha256,
            "status": obj.status,
            "created_at": obj.created_at,
        }
        for obj in objects
    ]


async def _upload_to_minio(bucket: str, key: str, content: bytes, content_type: str | None) -> bool:
    """上传文件到 MinIO。"""
    try:
        from io import BytesIO
        from minio import Minio

        client = Minio(
            settings.minio_endpoint.replace("http://", "").replace("https://", ""),
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_endpoint.startswith("https"),
        )
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        client.put_object(
            bucket,
            key,
            BytesIO(content),
            length=len(content),
            content_type=content_type or "application/octet-stream",
        )
        return True
    except Exception as exc:
        logger.error(f"MinIO upload failed: {exc}")
        return False
