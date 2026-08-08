"""
RiskAssessor — evalúa si un cambio propuesto sobre un dataset es seguro de
aplicar, combinando el `risk_level` de ImpactSimulator (blast radius) con
un `health_score` del propio downstream (qué fracción de los nodos
afectados tiene owner asignado).

No reemplaza ni modifica ImpactSimulator — lo consume tal cual (su
`risk_level` ya categórico) y agrega una segunda señal independiente que
ImpactSimulator no calcula: cuánto del downstream está "a la deriva" sin
nadie responsable. Un cambio con blast radius alto pero downstream 100%
ownership es más seguro de tocar (hay a quién avisar) que uno con el mismo
blast radius pero downstream sin owner (nadie se va a enterar hasta que
sea demasiado tarde).
"""

import logging
from typing import Any, Dict, List

from datahub.metadata.schema_classes import OwnershipClass

from config.settings import CHECK_CHANGE_RISK_THRESHOLD, DEFAULT_MAX_HOPS
from src.graph.client import DataHubClient
from src.graph.traversal import LineageTraversal

logger = logging.getLogger(__name__)

# risk_level (de ImpactSimulator) -> puntaje base, en la misma escala 0-1
# que health_score, para poder combinarlos. Igual criterio que
# _EVIDENCE_WEIGHTS en diagnoser.py: orden defendible, valores absolutos
# no calibrados contra incidentes reales.
_RISK_LEVEL_SCORE = {"none": 0.0, "low": 0.33, "medium": 0.66, "high": 1.0}

# Peso relativo del blast radius vs. la orfandad del downstream al combinar
# ambas señales en un solo risk_score. El blast radius pesa más porque un
# cambio que no afecta a nadie es seguro sin importar cuán "huérfano" esté
# el poco downstream que tenga.
_BLAST_RADIUS_WEIGHT = 0.6
_ORPHANHOOD_WEIGHT = 0.4


class RiskAssessor:
    """Decide si un cambio sobre un URN debe bloquearse antes de aplicarse."""

    def __init__(self, client: DataHubClient):
        if not client.is_connected:
            raise RuntimeError("DataHubClient no está conectado.")
        self.client = client
        self.traversal = LineageTraversal(client)

    def assess(self, urn: str, impact_report: Dict[str, Any]) -> Dict[str, Any]:
        """
        Combina `impact_report` (ya calculado por ImpactSimulator.simulate())
        con un health_score propio del downstream.

        Returns:
            Diccionario con health_score, risk_score (0-1), risk_label
            (BAJO/MEDIO/ALTO) y should_block (bool).
        """
        downstream_nodes = self.traversal.get_downstream(urn, max_hops=DEFAULT_MAX_HOPS)
        health_score = self._health_score(downstream_nodes)

        risk_level_score = _RISK_LEVEL_SCORE.get(impact_report["risk_level"], 0.0)
        orphanhood = 1.0 - health_score
        risk_score = round(
            _BLAST_RADIUS_WEIGHT * risk_level_score + _ORPHANHOOD_WEIGHT * orphanhood, 2
        )

        return {
            "urn": urn,
            "health_score": health_score,
            "risk_score": risk_score,
            "risk_label": self._risk_label(risk_score),
            "should_block": risk_score >= CHECK_CHANGE_RISK_THRESHOLD,
            "threshold": CHECK_CHANGE_RISK_THRESHOLD,
        }

    def _health_score(self, downstream_nodes: List[Dict[str, Any]]) -> float:
        """
        Fracción de nodos downstream CON al menos un owner asignado.
        1.0 = todo el downstream tiene owner (sano); 0.0 = nada lo tiene
        (nadie se entera si esto se rompe). Sin downstream, no hay nada
        que arriesgar: health_score neutro (1.0).
        """
        if not downstream_nodes:
            return 1.0

        owned = 0
        for node in downstream_nodes:
            ownership = self.client.graph.get_aspect(node["urn"], OwnershipClass)
            if ownership is not None and ownership.owners:
                owned += 1

        return round(owned / len(downstream_nodes), 2)

    @staticmethod
    def _risk_label(risk_score: float) -> str:
        if risk_score >= 0.67:
            return "ALTO"
        if risk_score >= 0.34:
            return "MEDIO"
        return "BAJO"
