"""Node lookup helpers shared by order materialization paths."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Node as NodeModel


async def resolve_node_id(db: AsyncSession, hostname: str) -> str:
    """Resolve a platform node UUID from the frozen external topology hostname."""
    result = await db.execute(select(NodeModel).where(NodeModel.hostname == hostname))
    node = result.scalar_one_or_none()
    if not node:
        raise ValueError(f"Node hostname not found: {hostname}")
    return node.id
