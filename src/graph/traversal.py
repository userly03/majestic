"""
Recorrido del grafo de linaje en DataHub.
Permite navegar upstream (hacia los orígenes) y downstream (hacia los
consumidores) usando un BFS de múltiples saltos sobre scroll_lineage.

API verificada contra acryl-datahub==1.7.0 (DataHubGraph.scroll_lineage,
datahub.ingestion.graph.openapi.LineageDirection) mediante introspección
directa del SDK instalado, no por documentación asumida — ver el
checklist de estado de validación técnica en proyecto-majestic.md sobre
"nombres de método que pueden variar entre versiones".
"""

import logging
from typing import Any, Dict, List

from datahub.ingestion.graph.openapi import LineageDirection

from src.graph.client import DataHubClient

logger = logging.getLogger(__name__)

_SCROLL_PAGE_SIZE = 100


class LineageTraversal:
    """Recorre el linaje de un dataset usando la API de DataHub."""

    def __init__(self, client: DataHubClient):
        if not client.is_connected:
            raise RuntimeError("DataHubClient no está conectado. Abortando traversal.")
        self.client = client

    def get_upstream(self, urn: str, max_hops: int = 3) -> List[Dict[str, Any]]:
        """Obtiene los datasets upstream (padres) de un URN dado, BFS hasta max_hops."""
        return self._bfs(urn, LineageDirection.UPSTREAM, max_hops)

    def get_downstream(self, urn: str, max_hops: int = 3) -> List[Dict[str, Any]]:
        """Obtiene los datasets downstream (hijos/consumidores) de un URN dado, BFS hasta max_hops."""
        return self._bfs(urn, LineageDirection.DOWNSTREAM, max_hops)

    def _bfs(
        self, root_urn: str, direction: LineageDirection, max_hops: int
    ) -> List[Dict[str, Any]]:
        logger.info(
            "🔍 Buscando %s de: %s (max %d hops)", direction.value, root_urn, max_hops
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
            logger.error("❌ Error en traversal %s: %s", direction.value, exc)
            return results

    def _one_hop(self, anchor_urn: str, direction: LineageDirection):
        """Genera tuplas (urn_del_otro_extremo, relationship_type, entity_type) a un salto de anchor_urn."""
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
