"""
Spike de validación: confirma el ciclo completo de memoria episódica
(escritura de structuredProperties + lectura de vuelta) contra una
instancia real de DataHub, antes de confiar en él para correr el agente.

Requiere que config/agent_memory_property.yaml ya haya sido aplicado:
    datahub properties upsert -f config/agent_memory_property.yaml

Uso:
    python3 scripts/spike_writeback_test.py [urn]

Si no se pasa un URN, usa el dataset de muestra que trae
`datahub docker quickstart` por defecto.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging

from src.graph.client import DataHubClient
from src.memory.writer import DiagnosisWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)

DEFAULT_TEST_URN = "urn:li:dataset:(urn:li:dataPlatform:hive,SampleHiveDataset,PROD)"

_FAKE_REPORT = {
    "pattern_signature": "spike_test:1:0:0",
    "reason": "Spike de validación de write-back — no es un diagnóstico real.",
    "confidence": 0.01,
}


def main() -> None:
    urn = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEST_URN
    print(f"🚀 Spike write-back sobre: {urn}")

    client = DataHubClient()
    if not client.is_connected:
        print("⚠️  No se pudo conectar. Ejecuta: datahub docker quickstart")
        sys.exit(1)

    writer = DiagnosisWriter(client)

    print("1/2 — Escribiendo diagnóstico de prueba...")
    wrote_ok = writer.write_report(
        urn, _FAKE_REPORT, business_context="Escrito por spike_writeback_test.py"
    )
    if not wrote_ok:
        print("❌ Falló la escritura. Revisa que agent_memory_property.yaml esté aplicado.")
        sys.exit(1)

    print("2/2 — Leyendo diagnóstico de vuelta...")
    read_back = writer.read_diagnosis(urn)

    if read_back and read_back["pattern_signature"] == _FAKE_REPORT["pattern_signature"]:
        print("🎉 ¡Éxito! El ciclo de memoria episódica funciona:")
        print(read_back)
    else:
        print("❌ La lectura no coincide con lo escrito (o vino vacía):")
        print(read_back)
        sys.exit(1)


if __name__ == "__main__":
    main()
