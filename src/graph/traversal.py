"""
Lineage graph traversal in DataHub.
Walks upstream (toward origins) and downstream (toward consumers) using a
multi-hop BFS over scroll_lineage.

API verified against acryl-datahub==1.7.0 (DataHubGraph.scroll_lineage,
datahub.ingestion.graph.openapi.LineageDirection) via direct introspection
of the installed SDK, not assumed from documentation — see the technical
validation checklist in docs/PITCH.md about "method names that can vary
between versions."
"""

import logging
from typing import Any, Dict, List

from datahub.ingestion.graph.openapi import LineageDirection

from src.graph.client import DataHubClient

logger = logging.getLogger(__name__)

_SCROLL_PAGE_SIZE = 100


class LineageTraversal:
    """Walks a dataset's lineage using DataHub's API."""

    def __init__(self, client: DataHubClient):
        if not client.is_connected:
            raise RuntimeError("DataHubClient is not connected. Aborting traversal.")
        self.client = client

    def get_upstream(self, urn: str, max_hops: int = 3) -> List[Dict[str, Any]]:
        """Gets the upstream (parent) datasets of a given URN, BFS up to max_hops."""
        return self._bfs(urn, LineageDirection.UPSTREAM, max_hops)

    def get_downstream(self, urn: str, max_hops: int = 3) -> List[Dict[str, Any]]:
        """Gets the downstream (child/consumer) datasets of a given URN, BFS up to max_hops."""
        return self._bfs(urn, LineageDirection.DOWNSTREAM, max_hops)

    def _bfs(
        self, root_urn: str, direction: LineageDirection, max_hops: int
    ) -> List[Dict[str, Any]]:
        logger.info(
            "Looking up %s from: %s (max %d hops)", direction.value, root_urn, max_hops
        )

        visited = {root_urn}
        results: List[Dict[str, Any]] = []
        frontier = [root_urn]

        try:
            for hop in range(1, max_hops + 1):
                if not frontier:
                    break
                next_frontier: List[str] = []

                for node_urn in frontier:
                    for other_urn, relationship_type, entity_type in self._one_hop(
                        node_urn, direction
                    ):
                        if other_urn in visited:
                            continue
                        visited.add(other_urn)
                        results.append(
                            {
                                "urn": other_urn,
                                "relationship_type": relationship_type,
                                "entity_type": entity_type,
                                "hop": hop,
                            }
                        )
                        next_frontier.append(other_urn)

                frontier = next_frontier

            return results
        except Exception as exc:
            logger.error("Error during %s traversal: %s", direction.value, exc)
            return results

    def _one_hop(self, anchor_urn: str, direction: LineageDirection):
        """Yields (other_end_urn, relationship_type, entity_type) tuples one hop from anchor_urn."""
        scroll_id = None
        while True:
            result = self.client.graph.scroll_lineage(
                urns=[anchor_urn],
                direction=direction,
                count=_SCROLL_PAGE_SIZE,
                scroll_id=scroll_id,
            )
            for rel in result.relationships:
                if rel.source_urn == anchor_urn:
                    other_urn, other_type = rel.destination_urn, rel.destination_entity_type
                else:
                    other_urn, other_type = rel.source_urn, rel.source_entity_type

                if other_urn != anchor_urn:
                    yield other_urn, rel.relationship_type, other_type

            scroll_id = result.scroll_id
            if scroll_id is None:
                break
