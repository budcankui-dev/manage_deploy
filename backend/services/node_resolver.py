"""Node lookup helpers shared by order materialization paths."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Node as NodeModel


async def resolve_node_id(db: AsyncSession, node_ref: str) -> str:
    """Resolve a platform node UUID from alias, topology id, or UUID.

    The router-facing protocol uses topology node ids, while the UI usually
    shows aliases such as h1/compute-1.  Accepting both keeps the integration
    explicit without forcing the router to know platform UUIDs.
    """
    result = await db.execute(
        select(NodeModel).where(
            NodeModel.deleted_at.is_(None),
            or_(
                NodeModel.id == node_ref,
                NodeModel.hostname == node_ref,
                NodeModel.topology_node_id == node_ref,
            ),
        )
    )
    node = result.scalar_one_or_none()
    if not node:
        raise ValueError(f"Node not found by alias/topology id: {node_ref}")
    return node.id
