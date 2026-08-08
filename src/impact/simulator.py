"""
Simulador de impacto downstream.
Antes de ejecutar un cambio crítico en un dataset, recorre el mismo
traversal que usa el diagnóstico (Fase 1) pero hacia abajo (downstream)
para estimar qué tablas, dashboards y owners se verían afectados.
"""

import logging
from typing import Any, Dict, List

from datahub.metadata.schema_classes import OwnershipClass

from config.settings import DEFAULT_MAX_HOPS
from src.graph.client import DataHubClient
from src.graph.traversal import LineageTraversal

logger = logging.getLogger(__name__)

# Umbrales de la heurística de riesgo: cualquier dashboard afectado ya es
# "alto" porque impacta directamente a consumidores de negocio; si no hay
# dashboards, el volumen de datasets downstream decide el nivel.
_HIGH_RISK_DATASET_THRESHOLD = 10
_MEDIUM_RISK_DATASET_THRESHOLD = 1


class ImpactSimulator:
    """Simula el impacto de un cambio recorriendo el linaje downstream."""

    def __init__(self, client: DataHubClient):
        if not client.is_connected:
            raise RuntimeError("DataHubClient no está conectado.")
        self.client = client
        self.traversal = LineageTraversal(client)

    def simulate(self, urn: str) -> Dict[str, Any]:
        """
        Calcula el impacto downstream de un cambio en el dataset dado.

        Returns:
            Diccionario con datasets, dashboards y owners afectados.
        """
        logger.info("⚡ Simulando impacto downstream para: %s", urn)

        downstream_nodes = self.traversal.get_downstream(urn, max_hops=DEFAULT_MAX_HOPS)

        affected_dashboards = [
            node for node in downstream_nodes if node["entity_type"] == "dashboard"
        ]
        affected_owners = self._collect_owners(downstream_nodes)

        impact_report = {
            "source_urn": urn,
            "affected_datasets": len(downstream_nodes),
            "affected_dashboards": len(affected_dashboards),
            "affected_owners": affected_owners,
            "risk_level": self._risk_level(len(downstream_nodes), len(affected_dashboards)),
        }

        logger.info("✅ Simulación completada: %s", impact_report)
        return impact_report

    def _collect_owners(self, downstream_nodes: List[Dict[str, Any]]) -> List[str]:
        owners = set()
        for node in downstream_nodes:
            ownership = self.client.graph.get_aspect(node["urn"], OwnershipClass)
            if ownership:
                owners.update(owner.owner for owner in ownership.owners)
        return sorted(owners)

    @staticmethod
    def _risk_level(affected_count: int, dashboard_count: int) -> str:
        if affected_count == 0:
            return "none"
        if dashboard_count > 0 or affected_count >= _HIGH_RISK_DATASET_THRESHOLD:
            return "high"
        if affected_count >= _MEDIUM_RISK_DATASET_THRESHOLD:
            return "medium"
        return "low"
