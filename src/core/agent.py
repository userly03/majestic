"""
Agente principal de Majestic.
Recibe una alerta o URN problemático, diagnostica la causa raíz
y devuelve un informe estructurado con la firma de patrón que la
Fase 3 (memoria) usará para reconocer el mismo caso en otra entidad.
"""

import logging
import re
from typing import Any, Dict, Optional

from config.settings import DEFAULT_MAX_HOPS
from src.core.diagnoser import RootCauseDiagnoser
from src.graph.client import DataHubClient
from src.graph.traversal import LineageTraversal

logger = logging.getLogger(__name__)

_PLATFORM_RE = re.compile(r"urn:li:dataPlatform:([^,]+)")


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
            "ranked_candidates": diagnosis["ranked_candidates"],
            "pattern_signature": self._build_pattern_signature(
                diagnosis, len(upstream_nodes), len(downstream_nodes), urn
            ),
        }

        logger.info("✅ Diagnóstico completado: %s", report)
        return report

    @staticmethod
    def _extract_platform(urn: Optional[str]) -> str:
        """Extrae la plataforma ('hive', 'snowflake', ...) de un URN de DataHub."""
        if not urn:
            return "unknown"
        match = _PLATFORM_RE.search(urn)
        return match.group(1) if match else "unknown"

    @staticmethod
    def _build_pattern_signature(
        diagnosis: Dict[str, Any],
        upstream_count: int,
        downstream_count: int,
        target_urn: str,
    ) -> str:
        """
        Firma determinista 'tipo_anomalia:profundidad:upstream:downstream:plataforma'
        (ver Fase 3 en proyecto-majestic.md). Permite reconocer la misma
        estructura causal en otra entidad sin volver a razonar desde cero.

        El componente de plataforma se agregó (2026-08-08, ver AUDIT_REPORT.md
        sección 1.4 y Sección 2 ítem 1) porque la firma sin él es demasiado
        gruesa: dos datasets completamente no relacionados en dominios
        distintos, con el mismo evidence_type/hop/upstream/downstream,
        producían la misma firma y el agente los trataba como el mismo
        incidente. Anclar a la plataforma del nodo causal es una mejora
        barata (el dato ya viene en el URN, sin llamada extra a DataHub) pero
        PARCIAL: dos datasets del mismo dominio de negocio pero distinta
        plataforma ya no colisionan, pero dos datasets de dominios distintos
        en la MISMA plataforma (p. ej. dos tablas Hive no relacionadas)
        todavía pueden hacerlo. Por eso `find_previous_diagnosis`
        (src/memory/writer.py) y el mensaje de reuso en `main.py` tratan
        siempre la coincidencia como "misma estructura", nunca como "mismo
        incidente confirmado" — ver la nota en cmd_diagnose.
        """
        causal_chain = diagnosis["causal_chain"]
        if not causal_chain:
            platform = MajesticAgent._extract_platform(target_urn)
            return f"unknown:0:{upstream_count}:{downstream_count}:{platform}"

        root_urn = diagnosis["root_cause_urn"]
        root_link = next(link for link in causal_chain if link["urn"] == root_urn)
        platform = MajesticAgent._extract_platform(root_urn)
        return (
            f"{root_link['evidence_type']}:{root_link['hop']}:"
            f"{upstream_count}:{downstream_count}:{platform}"
        )
