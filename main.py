"""
Entrypoint CLI de Majestic.

Uso:
    python3 main.py [--quiet] diagnose <urn> [--write] [--business-context "texto"] [--explain]
    python3 main.py [--quiet] impact <urn>
    python3 main.py doctor
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import requests

from src.core.agent import MajesticAgent
from src.core.narrator import explain
from src.graph.client import DataHubClient
from src.impact.simulator import ImpactSimulator
from src.memory.writer import DiagnosisWriter

logger = logging.getLogger(__name__)

MEMORY_PROPERTY_YAML = str(
    Path(__file__).resolve().parent / "config" / "agent_memory_property.yaml"
)
DOCTOR_TEST_URN = "urn:li:dataset:(urn:li:dataPlatform:hive,_majestic_doctor_check,PROD)"
_DOCTOR_REPORT = {
    "pattern_signature": "doctor_check:0:0:0",
    "reason": "Chequeo de `main.py doctor` — no es un diagnóstico real.",
    "confidence": 0.0,
}


def cmd_diagnose(
    client: DataHubClient, urn: str, write: bool, business_context: str, explain_flag: bool
) -> None:
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

    if explain_flag:
        print("\n📝 Explicación:")
        print(explain(report))

    if write:
        ok = writer.write_report(urn, report, business_context=business_context)
        print("\n💾 Write-back:", "OK" if ok else "FALLÓ")


def cmd_impact(client: DataHubClient, urn: str) -> None:
    simulator = ImpactSimulator(client)
    impact_report = simulator.simulate(urn)
    print("\n⚡ Simulación de impacto:")
    print(json.dumps(impact_report, indent=2, ensure_ascii=False))


def _doctor_check_properties(client: DataHubClient) -> bool:
    """Confirma que las structured properties de config/agent_memory_property.yaml
    estén registradas en DataHub; si faltan, intenta registrarlas."""
    from datahub.api.entities.structuredproperties.structuredproperties import (
        StructuredProperties,
    )
    from datahub.metadata.schema_classes import StructuredPropertyDefinitionClass

    definitions = StructuredProperties.from_yaml(MEMORY_PROPERTY_YAML)

    def _missing():
        return [
            d
            for d in definitions
            if client.graph.get_aspect(d.urn, StructuredPropertyDefinitionClass) is None
        ]

    missing = _missing()
    if not missing:
        print("  ✅ Las 5 structured properties ya están registradas.")
        return True

    print(
        f"  ⚠️  Faltan {len(missing)}/{len(definitions)} — registrando desde "
        f"{MEMORY_PROPERTY_YAML}..."
    )
    try:
        StructuredProperties.create(MEMORY_PROPERTY_YAML, client.graph)
    except Exception as exc:
        print(f"  ❌ No se pudieron registrar: {exc}")
        return False

    still_missing = _missing()
    if still_missing:
        print(f"  ❌ Siguen faltando: {[d.id for d in still_missing]}")
        return False

    print("  ✅ Registradas correctamente.")
    return True


def _doctor_check_write_read_cycle(client: DataHubClient) -> bool:
    """Ciclo rápido de escritura + lectura contra un URN de prueba dedicado,
    para confirmar permisos de escritura sin tocar datos reales."""
    from datahub.emitter.mcp import MetadataChangeProposalWrapper
    from datahub.metadata.schema_classes import DatasetPropertiesClass, StatusClass

    # Asegura que el URN de prueba exista como entidad antes de aplicar el patch
    # de structuredProperties (un PATCH sobre una entidad inexistente puede fallar).
    client.graph.emit_mcp(
        MetadataChangeProposalWrapper(
            entityUrn=DOCTOR_TEST_URN,
            aspect=DatasetPropertiesClass(
                name="_majestic_doctor_check",
                description="Entidad de prueba de `main.py doctor`. Seguro de ignorar/borrar.",
            ),
        )
    )
    client.graph.emit_mcp(
        MetadataChangeProposalWrapper(entityUrn=DOCTOR_TEST_URN, aspect=StatusClass(removed=False))
    )

    writer = DiagnosisWriter(client)
    if not writer.write_report(DOCTOR_TEST_URN, _DOCTOR_REPORT):
        print("  ❌ Falló la escritura.")
        return False

    read_back = writer.read_diagnosis(DOCTOR_TEST_URN)
    if read_back and read_back["pattern_signature"] == _DOCTOR_REPORT["pattern_signature"]:
        print("  ✅ Escritura y lectura confirmadas.")
        return True

    print(f"  ❌ La lectura no coincide con lo escrito: {read_back}")
    return False


def cmd_doctor() -> None:
    """Corre en un solo comando lo que antes eran 3 pasos manuales
    (spike_test.py + datahub properties upsert + spike_writeback_test.py)."""
    print("🩺 Majestic doctor — validando el setup antes de la demo\n")
    results: dict[str, bool] = {}

    print("1/3 — Conexión a DataHub...")
    client = DataHubClient()
    results["Conexión a DataHub"] = client.is_connected
    print("  ✅ Conectado" if client.is_connected else "  ❌ No se pudo conectar")

    if client.is_connected:
        print("\n2/3 — Structured properties registradas...")
        try:
            results["Structured properties registradas"] = _doctor_check_properties(client)
        except Exception as exc:
            print(f"  ❌ Error verificando properties: {exc}")
            results["Structured properties registradas"] = False

        print("\n3/3 — Ciclo de escritura/lectura...")
        try:
            results["Ciclo de escritura/lectura"] = _doctor_check_write_read_cycle(client)
        except Exception as exc:
            print(f"  ❌ Error en el ciclo de escritura/lectura: {exc}")
            results["Ciclo de escritura/lectura"] = False
    else:
        print("\n2/3 y 3/3 — Saltados (sin conexión).")
        results["Structured properties registradas"] = False
        results["Ciclo de escritura/lectura"] = False

    print("\n" + "=" * 50)
    print("Resumen:")
    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {name}")

    all_ok = all(results.values())
    if all_ok:
        print("\n🎉 Todo listo para la demo.")
    else:
        print("\n⚠️  Hay pasos pendientes antes de la demo — revisar los ❌ arriba.")
        if not results["Conexión a DataHub"]:
            print("   Ejecuta: datahub docker quickstart")

    sys.exit(0 if all_ok else 1)


def _human_error(exc: Exception) -> str:
    """Traduce excepciones típicas del SDK/red a un mensaje legible para la demo,
    en vez de dejar que se imprima un traceback crudo."""
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return "No se pudo conectar a DataHub (host inalcanzable o timeout). Ejecuta: datahub docker quickstart"

    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        if status == 404:
            return "Dataset no encontrado en DataHub. Revisá que el URN esté bien escrito."
        if status == 400:
            return "DataHub rechazó el URN por formato inválido. Revisá que sea un URN completo (ej. 'urn:li:dataset:(...)')."
        return f"DataHub respondió con un error HTTP {status}."

    if isinstance(exc, RuntimeError):
        return str(exc)

    return f"Error inesperado ({type(exc).__name__}): {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Majestic — agente de linaje y observabilidad de datos.")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=(
            "Suprime los logs internos (conexión, traversal, etc.) y deja solo "
            "el resultado final — pensado para compartir pantalla en una demo."
        ),
    )
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
    diagnose_parser.add_argument(
        "--explain",
        action="store_true",
        help=(
            "Redacta la cadena de evidencia en lenguaje natural. Hoy es una "
            "plantilla determinística (no llama a ningún LLM externo) — ver "
            "src/core/narrator.py."
        ),
    )

    impact_parser = subparsers.add_parser("impact", help="Simula el impacto downstream de un cambio.")
    impact_parser.add_argument("urn", help="URN del dataset a modificar.")

    subparsers.add_parser(
        "doctor",
        help="Valida conexión, structured properties y permisos de escritura en un solo comando.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    if args.command == "doctor":
        cmd_doctor()
        return

    client = DataHubClient()
    if not client.is_connected:
        logger.error("No se pudo conectar a DataHub. Ejecuta: datahub docker quickstart")
        sys.exit(1)

    try:
        if args.command == "diagnose":
            cmd_diagnose(client, args.urn, args.write, args.business_context, args.explain)
        elif args.command == "impact":
            cmd_impact(client, args.urn)
    except Exception as exc:
        logger.debug("Detalle completo del error", exc_info=True)
        print(f"\n❌ Error: {_human_error(exc)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
