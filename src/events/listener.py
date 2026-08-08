"""
Listener de incidentes "lite" — versión polling, no Kafka.

DataHub publica cada cambio del grafo a Kafka en tiempo real (Metadata
Change Log). Este módulo NO se conecta a ese stream — hace polling
periódico a la API REST de DataHub (vía el mismo `DataHubGraph` que usa
el resto del proyecto, no una llamada HTTP cruda) buscando datasets con
un tag de incidente que todavía no se hayan visto, y corre el pipeline
de diagnóstico completo (`MajesticAgent.diagnose`, que internamente usa
`RootCauseDiagnoser`) sobre cada uno apenas aparece.

Es deliberadamente la versión simple: sin Kafka, sin persistencia entre
reinicios (el set de URNs ya procesados vive solo en memoria — si el
proceso se reinicia, vuelve a diagnosticar lo que ya estaba tageado).
Suficiente para demostrar el patrón ("Majestic no espera que le
pregunten") sin la complejidad operativa de un consumer de Kafka real.

Uso:
    python3 -m src.events.listener              # loop infinito, poll cada
                                                  # LISTENER_POLL_INTERVAL_SECONDS
    python3 -m src.events.listener --once        # un solo ciclo (para tests/CI)
    python3 -m src.events.listener --interval 2  # override del intervalo
"""

import argparse
import logging
import time
from typing import Dict, Optional, Set

from config.settings import INCIDENT_TAG_KEYWORDS, LISTENER_POLL_INTERVAL_SECONDS
from src.core.agent import MajesticAgent
from src.core.diagnoser import RootCauseDiagnoser
from src.graph.client import DataHubClient

logger = logging.getLogger(__name__)


class IncidentListener:
    """
    Detecta datasets nuevos con tag de incidente y dispara el diagnóstico
    completo sobre cada uno, apenas una vez por URN.
    """

    def __init__(self, client: DataHubClient, poll_interval_seconds: Optional[float] = None):
        if not client.is_connected:
            raise RuntimeError("DataHubClient no está conectado.")
        self.client = client
        self.poll_interval_seconds = poll_interval_seconds or LISTENER_POLL_INTERVAL_SECONDS
        # Reutiliza la MISMA lógica de "¿este tag cuenta como incidente?"
        # que ya usa el diagnóstico normal (diagnoser.py), en vez de
        # reimplementar el chequeo acá y arriesgar que las dos copias se
        # desincronicen con el tiempo.
        self._diagnoser = RootCauseDiagnoser(client)
        self._agent = MajesticAgent(client)
        self._seen_urns: Set[str] = set()

    def poll_once(self) -> int:
        """
        Un solo ciclo: busca candidatos, diagnostica los nuevos.
        Returns: cantidad de incidentes nuevos procesados en este ciclo.
        """
        candidate_urns = self._find_candidate_urns()
        new_urns = sorted(candidate_urns - self._seen_urns)

        processed = 0
        for urn in new_urns:
            self._seen_urns.add(urn)

            # La búsqueda de texto libre puede traer falsos positivos
            # (la palabra "incident" en una descripción, no en un tag) —
            # confirmamos con el mismo chequeo real antes de diagnosticar.
            evidence = self._diagnoser._check_incident_tags(urn)
            if not evidence:
                logger.debug(
                    "%s coincidió en la búsqueda de texto pero no tiene un tag de "
                    "incidente real — se descarta.",
                    urn,
                )
                continue

            self._handle_new_incident(urn, evidence)
            processed += 1

        return processed

    def run(self, once: bool = False) -> None:
        logger.info(
            "🔔 Listener de incidentes iniciado (polling cada %ss, %s)",
            self.poll_interval_seconds,
            "un solo ciclo" if once else "loop continuo",
        )
        while True:
            try:
                self.poll_once()
            except Exception:
                logger.exception("Error en el ciclo de polling — se reintenta en el próximo ciclo.")

            if once:
                return
            time.sleep(self.poll_interval_seconds)

    def _find_candidate_urns(self) -> Set[str]:
        """
        Búsqueda de texto libre (mismo mecanismo que el Plan B de
        DiagnosisWriter._search_by_pattern_signature, ya validado contra
        una instancia real) por cada palabra clave de incidente, unida en
        un solo set de candidatos.
        """
        candidates: Set[str] = set()
        for keyword in INCIDENT_TAG_KEYWORDS:
            try:
                candidates.update(
                    self.client.graph.get_urns_by_filter(entity_types=["dataset"], query=keyword)
                )
            except Exception as exc:
                logger.warning("Búsqueda por palabra clave '%s' falló: %s", keyword, exc)
        return candidates

    def _handle_new_incident(self, urn: str, evidence: Dict) -> None:
        print(f"\n🔔 Incidente nuevo detectado: {urn}")
        print(f"   {evidence['evidence']}")

        report = self._agent.diagnose(urn)
        print("🩺 Diagnóstico automático:")
        print(f"   Causa raíz: {report['root_cause_urn'] or '(sin evidencia upstream)'}")
        print(f"   Razón: {report['reason']}")
        print(f"   Confianza: {report['confidence'] * 100:.0f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="Listener de incidentes de Majestic (polling, no Kafka).")
    parser.add_argument(
        "--once", action="store_true", help="Corre un solo ciclo de polling y termina (útil para tests)."
    )
    parser.add_argument(
        "--interval", type=float, default=None, help="Segundos entre ciclos (default: LISTENER_POLL_INTERVAL_SECONDS)."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    client = DataHubClient()
    if not client.is_connected:
        print("⚠️  No se pudo conectar a DataHub. Ejecuta: datahub docker quickstart")
        raise SystemExit(1)

    listener = IncidentListener(client, poll_interval_seconds=args.interval)
    listener.run(once=args.once)


if __name__ == "__main__":
    main()
