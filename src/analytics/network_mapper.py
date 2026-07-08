from __future__ import annotations

import logging

from src.storage.node_repository import NodeRepository

logger = logging.getLogger(__name__)


class NetworkMapper:
    """Network-level aggregates over the discovered-node table."""

    def __init__(self, node_repo: NodeRepository):
        self._node_repo = node_repo

    async def get_network_summary(self) -> dict:
        """Whole-table totals via SQL aggregates.

        The previous implementation summed over ``get_all()``, whose
        default LIMIT 500 silently capped every figure once the node
        table grew past it.
        """
        return await self._node_repo.get_network_totals()
