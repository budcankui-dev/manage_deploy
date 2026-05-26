"""Backend self-identity resolution.

Worker containers report metrics back to this Manager process via
`MANAGER_API_BASE`, which is derived from `settings.manager_public_url`.

Hard-coding `host.docker.internal` (or any other magic host) breaks any
non-Docker-Desktop deployment, so this module resolves the URL from the
`nodes` table at startup:

1. If the operator set `MANAGER_PUBLIC_URL` in env explicitly, that wins.
   This is the escape hatch for setups behind NAT / load balancers.
2. Otherwise we look up `settings.backend_hostname` (default `admin`) in
   the `nodes` table and build `http://<management_ip>:<backend_port>`.
3. If the hostname row does not exist, raise so startup fails loud.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from config import settings
from database import async_session_maker
from models import Node as NodeModel

logger = logging.getLogger(__name__)


class BackendSelfIdentityError(RuntimeError):
    """Raised when backend hostname cannot be resolved against the nodes table."""


async def resolve_manager_public_url() -> str:
    """Compute and cache `settings.manager_public_url` from the nodes table.

    Returns the resolved URL. Mutates `settings.manager_public_url` so that
    every consumer (`platform_runtime.build_platform_env` etc.) sees the
    same value without having to perform its own lookup at request time.
    """
    # Explicit override always wins.
    if settings.manager_public_url:
        logger.info(
            "MANAGER_PUBLIC_URL overridden by env: %s (skipping nodes-table lookup)",
            settings.manager_public_url,
        )
        return settings.manager_public_url

    hostname = settings.backend_hostname
    if not hostname:
        raise BackendSelfIdentityError(
            "BACKEND_HOSTNAME is empty; either set BACKEND_HOSTNAME env, "
            "register the backend host in the nodes table, or set "
            "MANAGER_PUBLIC_URL directly to bypass the lookup."
        )

    async with async_session_maker() as session:
        result = await session.execute(
            select(NodeModel).where(NodeModel.hostname == hostname)
        )
        node = result.scalar_one_or_none()

    if node is None:
        raise BackendSelfIdentityError(
            f"backend hostname {hostname!r} not found in nodes table; "
            "insert it (so its management_ip can be reused for worker callbacks) "
            "or set BACKEND_HOSTNAME env to an existing node, "
            "or set MANAGER_PUBLIC_URL directly to bypass the lookup."
        )

    mgmt_ip = (node.management_ip or "").strip()
    if not mgmt_ip:
        raise BackendSelfIdentityError(
            f"nodes row for hostname {hostname!r} has empty management_ip; "
            "update the row or set MANAGER_PUBLIC_URL directly to bypass the lookup."
        )

    url = f"http://{mgmt_ip}:{settings.backend_port}"
    settings.manager_public_url = url
    logger.info(
        "Resolved MANAGER_PUBLIC_URL=%s from nodes table (hostname=%s)", url, hostname
    )
    return url


__all__ = ["resolve_manager_public_url", "BackendSelfIdentityError"]
