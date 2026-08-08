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
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple, Type

from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlobalTagsClass,
    OwnershipClass,
    SchemaMetadataClass,
)

from config.settings import (
    EVIDENCE_WEIGHT_INCIDENT_TAG,
    EVIDENCE_WEIGHT_SCHEMA_CHANGE,
    EVIDENCE_WEIGHT_STALE_DATA,
    EVIDENCE_WEIGHT_UNOWNED,
    FRESHNESS_THRESHOLD_HOURS,
    INCIDENT_TAG_KEYWORDS,
    LAG_DECAY_HALFLIFE_HOURS,
    MAX_CAUSAL_LINKS,
    MAX_PARALLEL_REQUESTS,
    RANKED_CANDIDATES_TOP_K,
    UPSTREAM_INHERITANCE_DISCOUNT,
)
from src.graph.client import DataHubClient

logger = logging.getLogger(__name__)

# Peso relativo de cada tipo de evidencia: a mayor peso, más determinante
# se considera para señalar la causa raíz.
#
# IMPORTANTE — esto es un ranking razonado, no una calibración estadística:
# no existe (todavía) un dataset de incidentes reales resueltos contra el
# cual ajustar estos números, y docs/PROPOSAL.md es explícito en no fabricar una
# precisión que no se midió (mismo criterio que el proyecto ya aplica para
# no inventar "80% de probabilidad de fallo en 48h" sin datos históricos).
# Lo que sí se puede defender es el ORDEN relativo, por especificidad y
# fuerza causal de la señal:
#
#   incident_tag (0.9)   — señal explícita puesta por un humano; es la
#                          afirmación más directa posible de "esto es la
#                          causa", aunque el propio agente no la generó.
#   schema_change (0.7)  — cambio estructural real y con timestamp; fuerte,
#                          pero circunstancial (coincide en el tiempo, no
#                          prueba causalidad).
#   stale_data (0.5)     — ausencia de actualización; puede ser un ETL
#                          caído, pero también un fin de semana o una
#                          fuente que legítimamente actualiza poco.
#                          Señal más débil por más falsos positivos.
#   unowned (0.3)        — la más débil: no tener owner no rompe un
#                          pipeline por sí solo, solo dificulta escalar
#                          cuando algo más ya se rompió.
#
# Los valores absolutos por defecto (0.9/0.7/0.5/0.3) no están calibrados
# contra un dataset de incidentes reales — por eso son configurables vía
# config/settings.py (MAJESTIC_EVIDENCE_WEIGHT_*), no constantes fijas acá.
# Un equipo con historial real de incidentes puede recalibrarlos sin tocar
# este archivo. Ver "Notas técnicas" en README.md.
_EVIDENCE_WEIGHTS = {
    "incident_tag": EVIDENCE_WEIGHT_INCIDENT_TAG,
    "schema_change": EVIDENCE_WEIGHT_SCHEMA_CHANGE,
    "stale_data": EVIDENCE_WEIGHT_STALE_DATA,
    "unowned": EVIDENCE_WEIGHT_UNOWNED,
}


class RootCauseDiagnoser:
    """Analiza nodos del linaje y determina la causa raíz con evidencia trazable."""

    def __init__(self, client: DataHubClient):
        if not client.is_connected:
            raise RuntimeError("DataHubClient no está conectado. Abortando diagnóstico.")
        self.client = client
        # Cache por instancia de get_aspect: mismo (urn, tipo de aspecto) no
        # se pide dos veces mientras viva este RootCauseDiagnoser. Sin riesgo
        # de condición de carrera entre hops paralelos porque el BFS que
        # arma upstream_nodes ya deduplica URNs (visited set en traversal.py).
        self._aspect_cache: Dict[Tuple[str, type], Any] = {}

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

            urns_at_hop = nodes_by_hop[hop]
            evidences = self._collect_evidence_parallel(urns_at_hop)
            hop_evidence = [
                {"urn": urn, "hop": hop, **evidence}
                for urn, evidence in zip(urns_at_hop, evidences)
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
                "ranked_candidates": [],
            }

        self._apply_adjusted_weights(causal_chain)

        root_link = max(causal_chain, key=lambda link: (link["hop"], link["adjusted_weight"]))
        ranked_candidates = sorted(
            causal_chain, key=lambda link: (link["hop"], link["adjusted_weight"]), reverse=True
        )[:RANKED_CANDIDATES_TOP_K]

        return {
            "root_cause_urn": root_link["urn"],
            "reason": self._explain(root_link),
            "causal_chain": causal_chain,
            "confidence": self._confidence(causal_chain),
            "ranked_candidates": ranked_candidates,
        }

    def _collect_evidence_parallel(self, urns: List[str]) -> List[Optional[Dict[str, Any]]]:
        """
        Corre _collect_evidence para todos los URNs de un mismo hop en
        paralelo (hasta MAX_PARALLEL_REQUESTS a la vez) en vez de uno por
        uno. Con un solo nodo por hop (el caso común) es equivalente a la
        versión secuencial; el beneficio aparece en nodos con fan-in ancho.
        Devuelve los resultados en el mismo orden que `urns`.
        """
        if len(urns) <= 1:
            return [self._collect_evidence(urn) for urn in urns]

        with ThreadPoolExecutor(max_workers=min(len(urns), MAX_PARALLEL_REQUESTS)) as pool:
            return list(pool.map(self._collect_evidence, urns))

    def _get_aspect_cached(self, urn: str, aspect_type: Type) -> Any:
        key = (urn, aspect_type)
        if key not in self._aspect_cache:
            self._aspect_cache[key] = self.client.graph.get_aspect(urn, aspect_type)
        return self._aspect_cache[key]

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
        tags = self._get_aspect_cached(urn, GlobalTagsClass)
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
        schema = self._get_aspect_cached(urn, SchemaMetadataClass)
        if not schema or not schema.lastModified:
            return None
        age_hours = self._hours_since(schema.lastModified.time)
        if age_hours is not None and age_hours <= FRESHNESS_THRESHOLD_HOURS:
            return {
                "evidence_type": "schema_change",
                "evidence": f"schema modificado hace {age_hours:.1f}h (umbral {FRESHNESS_THRESHOLD_HOURS}h)",
                "weight": _EVIDENCE_WEIGHTS["schema_change"],
                "age_hours": age_hours,
            }
        return None

    def _check_staleness(self, urn: str) -> Optional[Dict[str, Any]]:
        props = self._get_aspect_cached(urn, DatasetPropertiesClass)
        if not props or not props.lastModified:
            return None
        age_hours = self._hours_since(props.lastModified.time)
        if age_hours is not None and age_hours > FRESHNESS_THRESHOLD_HOURS:
            return {
                "evidence_type": "stale_data",
                "evidence": f"sin actualizar hace {age_hours:.1f}h (umbral {FRESHNESS_THRESHOLD_HOURS}h)",
                "weight": _EVIDENCE_WEIGHTS["stale_data"],
                "age_hours": age_hours,
            }
        return None

    def _check_ownership(self, urn: str) -> Optional[Dict[str, Any]]:
        ownership = self._get_aspect_cached(urn, OwnershipClass)
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
    def _recency_decay(age_hours: Optional[float]) -> float:
        """
        Decaimiento exponencial por antigüedad — ver docs/LAG_AWARE_DIAGNOSIS.md.
        Evidencia con `age_hours=0` (recién ocurrida) no se descuenta; a
        medida que pasa el tiempo el peso decae hacia 0 sin llegar nunca a
        cero exacto. Sin `age_hours` (incident_tag, unowned: sin timestamp
        confiable disponible) no hay decaimiento — se devuelve 1.0.
        """
        if age_hours is None:
            return 1.0
        return 0.5 ** (max(age_hours, 0.0) / LAG_DECAY_HALFLIFE_HOURS)

    @staticmethod
    def _apply_adjusted_weights(causal_chain: List[Dict[str, Any]]) -> None:
        """
        Calcula `adjusted_weight` para cada eslabón de la cadena, mutando
        `causal_chain` in-place. Dos ajustes sobre el `weight` base (que
        NUNCA se modifica, para que siga siendo el peso "de catálogo" del
        tipo de evidencia):

        1. Decaimiento por antigüedad (`_recency_decay`), solo para
           evidencia con `age_hours` disponible.
        2. Descuento por herencia: si el mismo `evidence_type` aparece en
           un hop más lejano (más upstream), el hop más cercano al target
           probablemente está heredando el problema, no aportando una
           señal independiente — se multiplica por
           UPSTREAM_INHERITANCE_DISCOUNT.

        Ver docs/LAG_AWARE_DIAGNOSIS.md para el razonamiento completo.
        """
        for link in causal_chain:
            decay = RootCauseDiagnoser._recency_decay(link.get("age_hours"))
            link["adjusted_weight"] = round(link["weight"] * decay, 4)

        for link in causal_chain:
            inherited_from_further_upstream = any(
                other["evidence_type"] == link["evidence_type"] and other["hop"] > link["hop"]
                for other in causal_chain
            )
            if inherited_from_further_upstream:
                link["adjusted_weight"] = round(
                    link["adjusted_weight"] * UPSTREAM_INHERITANCE_DISCOUNT, 4
                )

    @staticmethod
    def _confidence(causal_chain: List[Dict[str, Any]]) -> float:
        """
        Heurística de confianza: promedio del peso AJUSTADO (decaimiento +
        descuento por herencia) de la cadena, con un pequeño bonus por cada
        eslabón adicional confirmado. No es una probabilidad calibrada —
        falta validarla contra incidentes reales.
        """
        avg_weight = sum(link["adjusted_weight"] for link in causal_chain) / len(causal_chain)
        chain_bonus = min(0.1 * (len(causal_chain) - 1), 0.2)
        return round(min(avg_weight + chain_bonus, 1.0), 2)
