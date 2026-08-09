"""
Siembra un tercer escenario de demo, pensado específicamente para mostrar
el mecanismo "lag-aware" (ver docs/LAG_AWARE_DIAGNOSIS.md) en el video —
`seed_demo_data.py` (A→B→C) no lo ejercita, porque solo tiene una
evidencia por diagnóstico.

Topología (fan-in, no lineal como A→B→C): dos datasets independientes,
`inventory_recent` e `inventory_legacy`, alimentan directamente al mismo
target `logistics_report` — mismo hop (1), mismo tipo de evidencia
(`stale_data`), incluso el mismo peso base (0.5). La única diferencia es
CUÁNDO se pusieron obsoletos:

  - inventory_recent: dejó de actualizarse hace ~30h (recién cruzó el
    umbral de staleness de 24h — "se acaba de romper").
  - inventory_legacy: lleva ~800h (~33 días) sin actualizarse — obsoleto
    crónico, probablemente un dataset de baja prioridad que nadie
    prioriza, no un incidente activo.

Sin el mecanismo lag-aware, ambos pesarían exactamente igual (0.5) y
`ranked_candidates` los mostraría empatados. Con el decaimiento por
antigüedad, `inventory_recent` debería rankear muy por encima de
`inventory_legacy` — ese contraste es el punto de la demo.

Uso:
    python3 scripts/seed_lag_aware_demo.py

Después de correrlo:
    python3 main.py diagnose "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.logistics_report,PROD)"

Nota: igual que seed_demo_data.py, la indexación de grafo/búsqueda de
DataHub es asíncrona — si el traversal no encuentra el lineage de
inmediato, esperar unos segundos y reintentar.
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
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    StatusClass,
    TimeStampClass,
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
URN_RECENT = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},majestic_demo.inventory_recent,PROD)"
URN_LEGACY = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},majestic_demo.inventory_legacy,PROD)"
URN_TARGET = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},majestic_demo.logistics_report,PROD)"
DASHBOARD_URN = "urn:li:dashboard:(looker,majestic_demo.logistics_dashboard)"

_ACTOR = "urn:li:corpuser:majestic_seed"

_RECENT_STALE_HOURS = 30  # recién cruzó el umbral de 24h
_LEGACY_STALE_HOURS = 800  # ~33 días, obsoleto crónico


def _audit_stamp() -> AuditStampClass:
    return AuditStampClass(time=int(time.time() * 1000), actor=_ACTOR)


def _hours_ago_millis(hours: float) -> int:
    return int(time.time() * 1000 - hours * 3600 * 1000)


def _emit(client: DataHubClient, urn: str, aspect) -> None:
    mcp = MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect)
    client.graph.emit_mcp(mcp)
    logger.info("  ✓ %s → %s", type(aspect).__name__, urn)


def seed(client: DataHubClient) -> None:
    print("1/3 — Creando inventory_recent (obsoleto hace ~30h) e inventory_legacy (obsoleto hace ~33 días)...")
    _emit(client, URN_RECENT, DatasetPropertiesClass(
        name="inventory_recent",
        description="[Majestic demo] Recién se puso obsoleto — señal de incidente activo.",
        lastModified=TimeStampClass(time=_hours_ago_millis(_RECENT_STALE_HOURS)),
    ))
    _emit(client, URN_RECENT, StatusClass(removed=False))
    _emit(client, URN_RECENT, OwnershipClass(
        owners=[OwnerClass(owner=_ACTOR, type=OwnershipTypeClass.TECHNICAL_OWNER)]
    ))

    _emit(client, URN_LEGACY, DatasetPropertiesClass(
        name="inventory_legacy",
        description="[Majestic demo] Obsoleto crónico — mismo tipo de evidencia que inventory_recent, pero mucho más viejo.",
        lastModified=TimeStampClass(time=_hours_ago_millis(_LEGACY_STALE_HOURS)),
    ))
    _emit(client, URN_LEGACY, StatusClass(removed=False))
    _emit(client, URN_LEGACY, OwnershipClass(
        owners=[OwnerClass(owner=_ACTOR, type=OwnershipTypeClass.TECHNICAL_OWNER)]
    ))

    _emit(client, URN_TARGET, DatasetPropertiesClass(
        name="logistics_report",
        description="[Majestic demo] Target del escenario lag-aware — dos causas candidatas al mismo hop.",
    ))
    _emit(client, URN_TARGET, StatusClass(removed=False))
    _emit(client, URN_TARGET, OwnershipClass(
        owners=[OwnerClass(owner=_ACTOR, type=OwnershipTypeClass.TECHNICAL_OWNER)]
    ))

    print("2/3 — Encadenando lineage: inventory_recent + inventory_legacy → logistics_report (fan-in, mismo hop)...")
    _emit(client, URN_TARGET, UpstreamLineageClass(upstreams=[
        UpstreamClass(dataset=URN_RECENT, type=DatasetLineageTypeClass.TRANSFORMED, auditStamp=_audit_stamp()),
        UpstreamClass(dataset=URN_LEGACY, type=DatasetLineageTypeClass.TRANSFORMED, auditStamp=_audit_stamp()),
    ]))

    print("3/3 — Creando dashboard downstream de logistics_report...")
    _emit(client, DASHBOARD_URN, DashboardInfoClass(
        title="[Majestic demo] Dashboard de Logística",
        description="Dashboard sintético del escenario lag-aware.",
        lastModified=ChangeAuditStampsClass(created=_audit_stamp(), lastModified=_audit_stamp()),
        datasets=[URN_TARGET],
    ))


def main() -> None:
    client = DataHubClient()
    if not client.is_connected:
        print("⚠️  No se pudo conectar. Ejecuta: datahub docker quickstart")
        sys.exit(1)

    print("🌱 Sembrando escenario lag-aware para Majestic...\n")
    seed(client)

    print(
        "\n🎉 Escenario sembrado. Diagnosticar logistics_report debería devolver "
        "2 candidatos rankeados con el mismo evidence_type (stale_data) y el mismo "
        "peso base (0.5) — pero inventory_recent (~30h obsoleto) debería rankear muy "
        "por encima de inventory_legacy (~800h obsoleto) gracias al decaimiento por antigüedad:"
    )
    print(f"   inventory_recent (reciente) {URN_RECENT}")
    print(f"   inventory_legacy (crónico)  {URN_LEGACY}")
    print(f"   logistics_report (target)   {URN_TARGET}")
    print(f"\nProbar con:")
    print(f'  python3 main.py diagnose "{URN_TARGET}"')
    print(
        "\nSi el traversal no encuentra el lineage de inmediato, esperar unos "
        "segundos (la indexación de grafo/búsqueda de DataHub es asíncrona) y reintentar."
    )


if __name__ == "__main__":
    main()
