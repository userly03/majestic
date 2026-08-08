"""
Módulo de escritura (write-back) en DataHub — Fase 3 del agente.
Persiste los diagnósticos generados por el agente como structuredProperties
sobre la entidad (ver config/agent_memory_property.yaml para la definición
de cada propiedad) y permite recuperar un diagnóstico previo cuando otra
entidad presenta la misma firma de patrón estructural.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from datahub.metadata.schema_classes import StructuredPropertiesClass
from datahub.specific.dataset import DatasetPatchBuilder

from src.graph.client import DataHubClient

logger = logging.getLogger(__name__)

# Deben coincidir con los `id` definidos en config/agent_memory_property.yaml.
_PROP_PATTERN_SIGNATURE = "majestic.patternSignature"
_PROP_DIAGNOSIS = "majestic.diagnosis"
_PROP_BUSINESS_CONTEXT = "majestic.businessContext"
_PROP_CONFIDENCE = "majestic.confidenceScore"
_PROP_DIAGNOSED_AT = "majestic.diagnosedAt"


class DiagnosisWriter:
    """Escribe y recupera diagnósticos persistidos como memoria episódica en DataHub."""

    def __init__(self, client: DataHubClient):
        if not client.is_connected:
            raise RuntimeError("DataHubClient no está conectado.")
        self.client = client

    def write_report(
        self,
        urn: str,
        report: Dict[str, Any],
        business_context: Optional[str] = None,
    ) -> bool:
        """
        Persiste un informe de diagnóstico en DataHub como structuredProperties.

        Args:
            urn: URN del dataset diagnosticado.
            report: Diccionario con el informe de causa raíz (ver MajesticAgent.diagnose).
            business_context: Texto libre opcional. Se omite si es None para no
                pisar contexto que un humano ya haya escrito al cerrar un incidente
                anterior con la misma firma.

        Returns:
            True si la escritura fue exitosa, False en caso contrario.
        """
        logger.info("💾 Escribiendo diagnóstico para %s en DataHub...", urn)

        try:
            patch = (
                DatasetPatchBuilder(urn)
                .add_structured_property(
                    _PROP_PATTERN_SIGNATURE, report["pattern_signature"]
                )
                .add_structured_property(_PROP_DIAGNOSIS, report["reason"])
                .add_structured_property(_PROP_CONFIDENCE, float(report["confidence"]))
                .add_structured_property(
                    _PROP_DIAGNOSED_AT, datetime.now(timezone.utc).isoformat()
                )
            )
            if business_context is not None:
                patch = patch.add_structured_property(
                    _PROP_BUSINESS_CONTEXT, business_context
                )

            self.client.graph.emit_mcps(patch.build())
            logger.info("✅ Diagnóstico persistido correctamente en %s", urn)
            return True
        except Exception as exc:
            logger.error("❌ Error escribiendo diagnóstico: %s", exc)
            return False

    def find_previous_diagnosis(
        self, pattern_signature: str, exclude_urn: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Busca una entidad ya diagnosticada con la misma firma de patrón
        estructural y devuelve su diagnóstico persistido, si existe.

        Nunca rompe el flujo del agente: si la búsqueda estructurada (Plan A)
        falla o no encuentra nada, cae a una búsqueda de texto libre (Plan B,
        ver _search_by_pattern_signature). Si ambos planes fallan, devuelve
        None como "no se encontró nada" en vez de propagar la excepción —
        no encontrar memoria previa no debería impedir diagnosticar.
        """
        candidate_urns = self._search_by_pattern_signature(pattern_signature)

        for candidate_urn in candidate_urns:
            if candidate_urn == exclude_urn:
                continue
            try:
                diagnosis = self.read_diagnosis(candidate_urn)
            except Exception as exc:
                logger.warning("No se pudo leer %s, se lo salta: %s", candidate_urn, exc)
                continue

            # Plan B es texto libre, así que puede traer falsos positivos
            # (coincidencias parciales) — confirmamos la firma exacta antes
            # de dar por buena la reutilización.
            if diagnosis and diagnosis.get("pattern_signature") == pattern_signature:
                logger.info(
                    "♻️  Firma '%s' ya vista en %s, reutilizando diagnóstico.",
                    pattern_signature,
                    candidate_urn,
                )
                return {"source_urn": candidate_urn, **diagnosis}

        return None

    def _search_by_pattern_signature(self, pattern_signature: str) -> List[str]:
        """
        Plan A: búsqueda estructurada por `extraFilters` sobre
        `structuredProperties.<qualifiedName>`. Es el mecanismo correcto,
        pero el nombre exacto del campo indexado depende de cómo DataHub
        mapea esa property en Elasticsearch — no confirmado contra una
        instancia real (ver README, sección "Notas técnicas").

        Plan B: si Plan A lanza una excepción, o "funciona" pero no trae
        resultados (que puede ser un true negative genuino, o el mapping
        de búsqueda silenciosamente distinto), se prueba una búsqueda de
        texto libre (`query=`) que no depende de ese nombre de campo.
        """
        try:
            urns = list(
                self.client.graph.get_urns_by_filter(
                    entity_types=["dataset"],
                    extraFilters=[
                        {
                            "field": f"structuredProperties.{_PROP_PATTERN_SIGNATURE}",
                            "values": [pattern_signature],
                            "condition": "EQUAL",
                        }
                    ],
                )
            )
            if urns:
                return urns
            logger.info(
                "Plan A (búsqueda estructurada) no encontró nada para '%s'; "
                "probando Plan B (texto libre) por si el campo de búsqueda "
                "no es el asumido.",
                pattern_signature,
            )
        except Exception as exc:
            logger.warning(
                "Plan A (búsqueda estructurada) falló (%s); probando Plan B (texto libre).",
                exc,
            )

        try:
            return list(
                self.client.graph.get_urns_by_filter(
                    entity_types=["dataset"],
                    query=pattern_signature,
                )
            )
        except Exception as exc:
            logger.error("❌ Plan B (texto libre) también falló: %s", exc)
            return []

    def read_diagnosis(self, urn: str) -> Optional[Dict[str, Any]]:
        """Lee de vuelta las structured properties de memoria persistidas sobre un URN."""
        aspect = self.client.graph.get_aspect(urn, StructuredPropertiesClass)
        if not aspect or not aspect.properties:
            return None

        values = {
            assignment.propertyUrn.split(":")[-1]: assignment.values
            for assignment in aspect.properties
        }
        if _PROP_PATTERN_SIGNATURE not in values:
            return None

        def first(key, default=None):
            found = values.get(key)
            return found[0] if found else default

        return {
            "pattern_signature": first(_PROP_PATTERN_SIGNATURE),
            "reason": first(_PROP_DIAGNOSIS),
            "confidence": first(_PROP_CONFIDENCE, 0.0),
            "diagnosed_at": first(_PROP_DIAGNOSED_AT),
            "business_context": first(_PROP_BUSINESS_CONTEXT),
        }
