"""
Motor de diagnóstico de causa raíz.
Recorre los nodos del linaje upstream, hop por hop, buscando evidencia
concreta en el grafo (no especulación): tags de incidente, datasets sin
owner, datos obsoletos o schemas modificados recientemente.

La cadena causal se extiende mientras haya evidencia en cada salto y se
detiene apenas un salto no aporta ninguna (o al llegar a
MAX_CAUSAL_LINKS). La causa raíz es el eslabón evidenciado más lejano:
es el que, siguiendo el patrón "detective ciego" del proyecto, suele
estar varios saltos upstream del síntoma original.
"""

import logging
import time as time_module
from typing import Any, Dict, List, Optional

from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlobalTagsClass,
    OwnershipClass,
    SchemaMetadataClass,
)

from config.settings import (
    FRESHNESS_THRESHOLD_HOURS,
    INCIDENT_TAG_KEYWORDS,
    MAX_CAUSAL_LINKS,
)
from src.graph.client import DataHubClient

logger = logging.getLogger(__name__)

# Peso relativo de cada tipo de evidencia: a mayor peso, más determinante
# se considera para señalar la causa raíz. Heurística de arranque, no un
# valor calibrado contra incidentes reales todavía.
_EVIDENCE_WEIGHTS = {
    "incident_tag": 0.9,
    "schema_change": 0.7,
    "stale_data": 0.5,
    "unowned": 0.3,
}


class RootCauseDiagnoser:
    """Analiza nodos del linaje y determina la causa raíz con evidencia trazable."""

    def __init__(self, client: DataHubClient):
        if not client.is_connected:
            raise RuntimeError("DataHubClient no está conectado. Abortando diagnóstico.")
        self.client = client

    def analyze(self, upstream_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Dada una lista de nodos upstream (con 'urn' y 'hop'), retorna el
        diagnóstico: causa raíz, cadena causal evidenciada y confianza.
        """
        logger.info("🔬 Analizando %d nodos upstream...", len(upstream_nodes))

        nodes_by_hop: Dict[int, List[str]] = {}
        for node in upstream_nodes:
            nodes_by_hop.setdefault(node["hop"], []).append(node["urn"])

        causal_chain: List[Dict[str, Any]] = []
        for hop in sorted(nodes_by_hop):
            if len(causal_chain) >= MAX_CAUSAL_LINKS:
                break

            hop_evidence = [
                {"urn": urn, "hop": hop, **evidence}
                for urn in nodes_by_hop[hop]
                for evidence in [self._collect_evidence(urn)]
                if evidence is not None
            ]
            if not hop_evidence:
                logger.info("⛔ Sin evidencia en hop %d, la cadena se detiene ahí.", hop)
                break

            causal_chain.extend(hop_evidence)

        if not causal_chain:
            return {
                "root_cause_urn": None,
                "reason": "No se encontró evidencia concreta en el grafo upstream.",
                "causal_chain": [],
                "confidence": 0.0,
            }

        root_link = max(causal_chain, key=lambda link: (link["hop"], link["weight"]))

        return {
            "root_cause_urn": root_link["urn"],
            "reason": self._explain(root_link),
            "causal_chain": causal_chain,
            "confidence": self._confidence(causal_chain),
        }

    def _collect_evidence(self, urn: str) -> Optional[Dict[str, Any]]:
        """Busca evidencia concreta (tag, owner, freshness, schema) sobre un URN."""
        tag_evidence = self._check_incident_tags(urn)
        if tag_evidence:
            return tag_evidence

        schema_evidence = self._check_recent_schema_change(urn)
        if schema_evidence:
            return schema_evidence

        freshness_evidence = self._check_staleness(urn)
        if freshness_evidence:
            return freshness_evidence

        ownership_evidence = self._check_ownership(urn)
        if ownership_evidence:
            return ownership_evidence

        return None

    def _check_incident_tags(self, urn: str) -> Optional[Dict[str, Any]]:
        tags = self.client.graph.get_aspect(urn, GlobalTagsClass)
        if not tags:
            return None
        for assoc in tags.tags:
            tag_lower = assoc.tag.lower()
            for keyword in INCIDENT_TAG_KEYWORDS:
                if keyword in tag_lower:
                    return {
                        "evidence_type": "incident_tag",
                        "evidence": f"tag '{assoc.tag}' coincide con palabra clave de incidente '{keyword}'",
                        "weight": _EVIDENCE_WEIGHTS["incident_tag"],
                    }
        return None

    def _check_recent_schema_change(self, urn: str) -> Optional[Dict[str, Any]]:
        schema = self.client.graph.get_aspect(urn, SchemaMetadataClass)
        if not schema or not schema.lastModified:
            return None
        age_hours = self._hours_since(schema.lastModified.time)
        if age_hours is not None and age_hours <= FRESHNESS_THRESHOLD_HOURS:
            return {
                "evidence_type": "schema_change",
                "evidence": f"schema modificado hace {age_hours:.1f}h (umbral {FRESHNESS_THRESHOLD_HOURS}h)",
                "weight": _EVIDENCE_WEIGHTS["schema_change"],
            }
        return None

    def _check_staleness(self, urn: str) -> Optional[Dict[str, Any]]:
        props = self.client.graph.get_aspect(urn, DatasetPropertiesClass)
        if not props or not props.lastModified:
            return None
        age_hours = self._hours_since(props.lastModified.time)
        if age_hours is not None and age_hours > FRESHNESS_THRESHOLD_HOURS:
            return {
                "evidence_type": "stale_data",
                "evidence": f"sin actualizar hace {age_hours:.1f}h (umbral {FRESHNESS_THRESHOLD_HOURS}h)",
                "weight": _EVIDENCE_WEIGHTS["stale_data"],
            }
        return None

    def _check_ownership(self, urn: str) -> Optional[Dict[str, Any]]:
        ownership = self.client.graph.get_aspect(urn, OwnershipClass)
        if ownership is not None and not ownership.owners:
            return {
                "evidence_type": "unowned",
                "evidence": "dataset sin owner asignado",
                "weight": _EVIDENCE_WEIGHTS["unowned"],
            }
        return None

    @staticmethod
    def _hours_since(epoch_millis: int) -> Optional[float]:
        if not epoch_millis:
            return None
        now_millis = time_module.time() * 1000
        return (now_millis - epoch_millis) / (1000 * 60 * 60)

    @staticmethod
    def _explain(link: Dict[str, Any]) -> str:
        return f"{link['urn']} (hop {link['hop']}): {link['evidence']}"

    @staticmethod
    def _confidence(causal_chain: List[Dict[str, Any]]) -> float:
        """
        Heurística de confianza: promedio del peso de evidencia de la cadena,
        con un pequeño bonus por cada eslabón adicional confirmado. No es una
        probabilidad calibrada — falta validarla contra incidentes reales.
        """
        avg_weight = sum(link["weight"] for link in causal_chain) / len(causal_chain)
        chain_bonus = min(0.1 * (len(causal_chain) - 1), 0.2)
        return round(min(avg_weight + chain_bonus, 1.0), 2)
