"""Resolve user-entered business endpoints to known topology nodes."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Node


class EndpointResolutionError(ValueError):
    """Raised when a user endpoint is not registered as a routable data-plane node."""


@dataclass(frozen=True)
class ResolvedEndpoint:
    input_value: str
    topology_node_id: str
    topology_alias: str
    business_ip: str | None
    business_ipv6: str | None

    def model_dump(self) -> dict[str, str | None]:
        return {
            "input_value": self.input_value,
            "topology_node_id": self.topology_node_id,
            "topology_alias": self.topology_alias,
            "business_ip": self.business_ip,
            "business_ipv6": self.business_ipv6,
        }


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _identity_for(node: Node, raw_value: str) -> ResolvedEndpoint:
    topology_id = _clean(node.topology_node_id) or node.hostname
    return ResolvedEndpoint(
        input_value=raw_value,
        topology_node_id=topology_id,
        topology_alias=node.hostname,
        business_ip=_clean(node.business_ip) or None,
        business_ipv6=_clean(node.business_ipv6) or None,
    )


async def resolve_user_endpoint(db: AsyncSession, value: str) -> ResolvedEndpoint:
    """Resolve a user-supplied endpoint name or data-plane IP.

    The accepted identifiers are topology alias/hostname, topology node id,
    business IPv4, and business IPv6. Management IP is intentionally excluded:
    user traffic and router DAGs must use data-plane addresses.
    """

    text = _clean(value)
    if not text:
        raise EndpointResolutionError("端点不能为空，请填写已登记的终端别名、拓扑节点 ID 或业务面 IP")

    row = await db.execute(
        select(Node)
        .where(
            Node.deleted_at.is_(None),
            or_(
                Node.hostname == text,
                Node.topology_node_id == text,
                Node.business_ip == text,
                Node.business_ipv6 == text,
            ),
        )
        .limit(1)
    )
    node = row.scalar_one_or_none()
    if node is None:
        raise EndpointResolutionError(f"端点未登记为业务面拓扑节点：{text}")
    return _identity_for(node, text)
