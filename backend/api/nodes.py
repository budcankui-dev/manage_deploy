from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import ipaddress
import re

from database import get_db
from agents.agent_client import AgentClient
from models import Node as NodeModel, TaskInstanceNode
from schemas import (
    NodeCreate,
    NodeUpdate,
    NodeResponse,
    NodeSimple,
    OrphanContainerResponse,
    OrphanCleanupRequest,
    OrphanCleanupResponse,
)

router = APIRouter(prefix="/api/nodes", tags=["nodes"])
MANAGED_CONTAINER_PATTERN = re.compile(r"^[0-9a-f-]{36}_[0-9a-f-]{36}$")


def _get_node_endpoint(node: NodeModel) -> str:
    return node.agent_address or node.management_ip


async def _load_node_or_404(db: AsyncSession, node_id: str) -> NodeModel:
    result = await db.execute(select(NodeModel).where(NodeModel.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


async def _list_orphan_containers(db: AsyncSession, node: NodeModel) -> list[OrphanContainerResponse]:
    success, result = await AgentClient().list_managed_containers(_get_node_endpoint(node))
    if not success:
        raise HTTPException(status_code=500, detail=result.get("error") or "Failed to list managed containers")

    known_result = await db.execute(
        select(TaskInstanceNode.container_name).where(TaskInstanceNode.node_id == node.id)
    )
    known_names = {name for name in known_result.scalars().all() if name}

    orphans: list[OrphanContainerResponse] = []
    for item in result.get("containers", []):
        container_name = item.get("container_name") or ""
        if not MANAGED_CONTAINER_PATTERN.match(container_name):
            continue
        if container_name in known_names:
            continue
        orphans.append(
            OrphanContainerResponse(
                container_id=item.get("container_id") or "",
                container_name=container_name,
                status=item.get("status") or "unknown",
                image=item.get("image") or "-",
                ports=item.get("ports"),
                reason="数据库中已不存在对应实例节点",
            )
        )
    return orphans


@router.post("", response_model=NodeResponse)
async def create_node(
    node: NodeCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        ipaddress.IPv4Address(node.management_ip)
    except ValueError:
        raise HTTPException(status_code=400, detail="management_ip must be a valid IPv4 address")

    db_node = NodeModel(**node.model_dump())
    db.add(db_node)
    await db.commit()
    await db.refresh(db_node)
    return db_node


@router.get("", response_model=list[NodeSimple])
async def list_nodes(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(NodeModel))
    nodes = result.scalars().all()
    return nodes


@router.get("/{node_id}", response_model=NodeResponse)
async def get_node(
    node_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(NodeModel).where(NodeModel.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.put("/{node_id}", response_model=NodeResponse)
async def update_node(
    node_id: str,
    node: NodeUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(NodeModel).where(NodeModel.id == node_id))
    db_node = result.scalar_one_or_none()
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")

    update_data = node.model_dump(exclude_unset=True)
    if "management_ip" in update_data:
        try:
            ipaddress.IPv4Address(update_data["management_ip"])
        except ValueError:
            raise HTTPException(status_code=400, detail="management_ip must be a valid IPv4 address")

    for field, value in update_data.items():
        setattr(db_node, field, value)

    await db.commit()
    await db.refresh(db_node)
    return db_node


@router.post("/{node_id}/sync-resources", response_model=NodeResponse)
async def sync_node_resources(
    node_id: str,
    db: AsyncSession = Depends(get_db),
):
    node = await _load_node_or_404(db, node_id)
    success, result = await AgentClient().get_resources(_get_node_endpoint(node))
    if not success:
        raise HTTPException(
            status_code=502,
            detail=result.get("error") or "Failed to query node resources",
        )

    for field in (
        "gpu_count",
        "gpu_model",
        "gpu_memory_mb",
        "cpu_model",
        "cpu_cores",
        "memory_mb",
        "driver_version",
        "cuda_version",
    ):
        if field in result:
            setattr(node, field, result[field])

    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
    if diagnostics.get("nvidia_smi_error") and not result.get("cuda_version"):
        node.resource_note = "节点资源已同步；未检测到 CUDA 版本，请确认 nvidia-smi 或 NVIDIA 驱动环境。"
    elif not node.resource_note or "未检测到 CUDA" in node.resource_note:
        node.resource_note = None

    await db.commit()
    await db.refresh(node)
    return node


@router.delete("/{node_id}")
async def delete_node(
    node_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(NodeModel).where(NodeModel.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    await db.delete(node)
    await db.commit()
    return {"message": "Node deleted"}


@router.get("/{node_id}/orphans", response_model=list[OrphanContainerResponse])
async def list_node_orphans(
    node_id: str,
    db: AsyncSession = Depends(get_db),
):
    node = await _load_node_or_404(db, node_id)
    return await _list_orphan_containers(db, node)


@router.post("/{node_id}/orphans/cleanup", response_model=OrphanCleanupResponse)
async def cleanup_node_orphans(
    node_id: str,
    request: OrphanCleanupRequest,
    db: AsyncSession = Depends(get_db),
):
    node = await _load_node_or_404(db, node_id)
    current_orphans = await _list_orphan_containers(db, node)
    allowed_names = {item.container_name for item in current_orphans}
    target_names = request.container_names or list(allowed_names)

    succeeded: list[str] = []
    failed: dict[str, str] = {}
    client = AgentClient()

    for container_name in target_names:
        if container_name not in allowed_names:
            failed[container_name] = "Container is not a current orphan managed by this node"
            continue
        success, result = await client.delete_container_by_name(_get_node_endpoint(node), container_name)
        if success:
            succeeded.append(container_name)
        else:
            failed[container_name] = result.get("error") or "Failed to delete container"

    return OrphanCleanupResponse(succeeded=succeeded, failed=failed)
