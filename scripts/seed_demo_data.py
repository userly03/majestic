"""
Sembrado de datos sintéticos para la demo de Majestic (Ronda 1, ítem 3.1
de docs/PROPOSAL.md).

Crea un mini-grafo de lineage garantizado: A → B → C, con una anomalía
real en B (sin owner + tag de incidente) para que diagnosticar C
encuentre una causa raíz *siempre*, sin depender de que el datapack de
`datahub docker quickstart` tenga algo interesante por casualidad. También
crea un dashboard downstream de C para que `main.py impact` tenga algo
que contar.

Uso:
    python3 scripts/seed_demo_data.py

Después de correrlo:
    python3 main.py diagnose "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)"
    python3 main.py impact   "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)"

Nota: la indexación de grafo/búsqueda en DataHub es asíncrona (vía Kafka).
Si el traversal no encuentra el lineage inmediatamente después de correr
este script, esperar unos segundos y reintentar.
"""

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    ChangeAuditStampsClass,
    DashboardInfoClass,
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    GlobalTagsClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    StatusClass,
    TagAssociationClass,
    TagPropertiesClass,
    UpstreamClass,
    UpstreamLineageClass,
)

from src.graph.client import DataHubClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

PLATFORM = "hive"
URN_A = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},majestic_demo.raw_marketing,PROD)"
URN_B = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},majestic_demo.marketing_etl,PROD)"
URN_C = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},majestic_demo.sales_report,PROD)"
DASHBOARD_URN = "urn:li:dashboard:(looker,majestic_demo.sales_dashboard)"
TAG_URN = "urn:li:tag:majestic_demo_incident"

_ACTOR = "urn:li:corpuser:majestic_seed"


def _audit_stamp() -> AuditStampClass:
    return AuditStampClass(time=int(time.time() * 1000), actor=_ACTOR)


def _emit(client: DataHubClient, urn: str, aspect) -> None:
    mcp = MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect)
    client.graph.emit_mcp(mcp)
    logger.info("  ✓ %s → %s", type(aspect).__name__, urn)


def seed(client: DataHubClient) -> None:
    print("1/4 — Creando datasets A (sano) → B (anomalía) → C (target)...")
    _emit(client, URN_A, DatasetPropertiesClass(
        name="raw_marketing",
        description="[Majestic demo] Datos crudos de marketing. Nodo sano: tiene owner, sin tags de incidente.",
    ))
    _emit(client, URN_A, StatusClass(removed=False))
    _emit(client, URN_A, OwnershipClass(
        owners=[OwnerClass(owner=_ACTOR, type=OwnershipTypeClass.TECHNICAL_OWNER)]
    ))

    _emit(client, URN_B, DatasetPropertiesClass(
        name="marketing_etl",
        description="[Majestic demo] ETL intermedio. Acá vive la anomalía: sin owner y con tag de incidente, a propósito.",
    ))
    _emit(client, URN_B, StatusClass(removed=False))
    _emit(client, URN_B, OwnershipClass(owners=[]))  # anomalía: sin owner, deliberado

    _emit(client, URN_C, DatasetPropertiesClass(
        name="sales_report",
        description="[Majestic demo] Reporte de ventas. Es el URN que se diagnostica en la demo.",
    ))
    _emit(client, URN_C, StatusClass(removed=False))
    _emit(client, URN_C, OwnershipClass(
        owners=[OwnerClass(owner=_ACTOR, type=OwnershipTypeClass.TECHNICAL_OWNER)]
    ))

    print("2/4 — Encadenando lineage A → B → C...")
    _emit(client, URN_B, UpstreamLineageClass(upstreams=[
        UpstreamClass(dataset=URN_A, type=DatasetLineageTypeClass.TRANSFORMED, auditStamp=_audit_stamp())
    ]))
    _emit(client, URN_C, UpstreamLineageClass(upstreams=[
        UpstreamClass(dataset=URN_B, type=DatasetLineageTypeClass.TRANSFORMED, auditStamp=_audit_stamp())
    ]))

    print("3/4 — Marcando la anomalía en B con un tag de incidente...")
    _emit(client, TAG_URN, TagPropertiesClass(
        name="Majestic Demo: Incidente",
        description="Tag sintético para la demo de Majestic: marca un dataset bajo investigación por un incidente de datos.",
    ))
    _emit(client, URN_B, GlobalTagsClass(tags=[TagAssociationClass(tag=TAG_URN)]))

    print("4/4 — Creando dashboard downstream de C (para `main.py impact`)...")
    _emit(client, DASHBOARD_URN, DashboardInfoClass(
        title="[Majestic demo] Dashboard de Ventas",
        description="Dashboard sintético que consume sales_report, para que el simulador de impacto tenga algo que contar.",
        lastModified=ChangeAuditStampsClass(created=_audit_stamp(), lastModified=_audit_stamp()),
        datasets=[URN_C],
    ))


def main() -> None:
    client = DataHubClient()
    if not client.is_connected:
        print("⚠️  No se pudo conectar. Ejecuta: datahub docker quickstart")
        sys.exit(1)

    print("🌱 Sembrando grafo de demo para Majestic...\n")
    seed(client)

    print("\n🎉 Grafo sembrado. Diagnosticar C debería encontrar la causa raíz en B (hop 1, incident_tag):")
    print(f"   A (sano)          {URN_A}")
    print(f"   B (anomalía)      {URN_B}")
    print(f"   C (target)        {URN_C}")
    print(f"   Dashboard         {DASHBOARD_URN}")
    print(f"\nProbar con:")
    print(f'  python3 main.py diagnose "{URN_C}"')
    print(f'  python3 main.py impact "{URN_C}"')
    print(
        "\nSi el traversal no encuentra el lineage de inmediato, esperar unos "
        "segundos (la indexación de grafo/búsqueda de DataHub es asíncrona) y reintentar."
    )


if __name__ == "__main__":
    main()
