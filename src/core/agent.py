"""
Agente principal de Majestic.
Recibe una alerta o URN problemático, diagnostica la causa raíz
y devuelve un informe estructurado con la firma de patrón que la
Fase 3 (memoria) usará para reconocer el mismo caso en otra entidad.
"""

import logging
from typing import Any, Dict

from config.settings import DEFAULT_MAX_HOPS
from src.core.diagnoser import RootCauseDiagnoser
from src.graph.client import DataHubClient
from src.graph.traversal import LineageTraversal

logger = logging.getLogger(__name__)


class MajesticAgent:
    """Orquestador principal del diagnóstico de causa raíz."""

    def __init__(self, client: DataHubClient):
        self.client = client
        self.traversal = LineageTraversal(client)
        self.diagnoser = RootCauseDiagnoser(client)
        logger.info("🧠 Agente Majestic inicializado")

    def diagnose(self, urn: str) -> Dict[str, Any]:
        """
        Ejecuta el pipeline completo de diagnóstico para un URN dado.

        Pasos:
            1. Recorrer upstream (y downstream, para la firma estructural).
            2. Cruzar owners, schemas y tags buscando evidencia real (Fase 2).
            3. Devolver el informe; la persistencia en el grafo es responsabilidad
               de DiagnosisWriter (Fase 3), no de este método.
        """
        logger.info("🩺 Iniciando diagnóstico para: %s", urn)

        upstream_nodes = self.traversal.get_upstream(urn, max_hops=DEFAULT_MAX_HOPS)
        downstream_nodes = self.traversal.get_downstream(urn, max_hops=DEFAULT_MAX_HOPS)

        diagnosis = self.diagnoser.analyze(upstream_nodes)

        report = {
            "target_urn": urn,
            "upstream_count": len(upstream_nodes),
            "downstream_count": len(downstream_nodes),
            "root_cause_urn": diagnosis["root_cause_urn"],
            "reason": diagnosis["reason"],
            "causal_chain": diagnosis["causal_chain"],
            "confidence": diagnosis["confidence"],
            "pattern_signature": self._build_pattern_signature(
                diagnosis, len(upstream_nodes), len(downstream_nodes)
            ),
        }

        logger.info("✅ Diagnóstico completado: %s", report)
        return report

    @staticmethod
    def _build_pattern_signature(
        diagnosis: Dict[str, Any], upstream_count: int, downstream_count: int
    ) -> str:
        """
        Firma determinista 'tipo_anomalia:profundidad:upstream:downstream'
        (ver Fase 3 en proyecto-majestic.md). Permite reconocer la misma
        estructura causal en otra entidad sin volver a razonar desde cero.
        """
        causal_chain = diagnosis["causal_chain"]
        if not causal_chain:
            return f"unknown:0:{upstream_count}:{downstream_count}"

        root_urn = diagnosis["root_cause_urn"]
        root_link = next(link for link in causal_chain if link["urn"] == root_urn)
        return (
            f"{root_link['evidence_type']}:{root_link['hop']}:"
            f"{upstream_count}:{downstream_count}"
        )
