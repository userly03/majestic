"""
Entrypoint CLI de Majestic.

Uso:
    python3 main.py diagnose <urn> [--write] [--business-context "texto"]
    python3 main.py impact <urn>
"""

import argparse
import json
import logging
import sys

from src.core.agent import MajesticAgent
from src.graph.client import DataHubClient
from src.impact.simulator import ImpactSimulator
from src.memory.writer import DiagnosisWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def cmd_diagnose(client: DataHubClient, urn: str, write: bool, business_context: str) -> None:
    agent = MajesticAgent(client)
    writer = DiagnosisWriter(client)

    report = agent.diagnose(urn)

    previous = writer.find_previous_diagnosis(
        report["pattern_signature"], exclude_urn=urn
    )
    if previous:
        print("\n♻️  Ya existe un diagnóstico con esta firma de patrón en otra entidad:")
        print(json.dumps(previous, indent=2, ensure_ascii=False))

    print("\n🩺 Diagnóstico:")
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if write:
        ok = writer.write_report(urn, report, business_context=business_context)
        print("\n💾 Write-back:", "OK" if ok else "FALLÓ")


def cmd_impact(client: DataHubClient, urn: str) -> None:
    simulator = ImpactSimulator(client)
    impact_report = simulator.simulate(urn)
    print("\n⚡ Simulación de impacto:")
    print(json.dumps(impact_report, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Majestic — agente de linaje y observabilidad de datos.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    diagnose_parser = subparsers.add_parser("diagnose", help="Diagnostica la causa raíz de un URN.")
    diagnose_parser.add_argument("urn", help="URN del dataset a diagnosticar.")
    diagnose_parser.add_argument(
        "--write", action="store_true", help="Persiste el diagnóstico en DataHub."
    )
    diagnose_parser.add_argument(
        "--business-context",
        default=None,
        help="Contexto de negocio / lección aprendida a guardar junto al diagnóstico.",
    )

    impact_parser = subparsers.add_parser("impact", help="Simula el impacto downstream de un cambio.")
    impact_parser.add_argument("urn", help="URN del dataset a modificar.")

    args = parser.parse_args()

    client = DataHubClient()
    if not client.is_connected:
        logger.error("No se pudo conectar a DataHub. Ejecuta: datahub docker quickstart")
        sys.exit(1)

    if args.command == "diagnose":
        cmd_diagnose(client, args.urn, args.write, args.business_context)
    elif args.command == "impact":
        cmd_impact(client, args.urn)


if __name__ == "__main__":
    main()
