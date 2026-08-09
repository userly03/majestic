"""
Seeds a third demo scenario, designed specifically to show off the
"lag-aware" mechanism (see docs/LAG_AWARE_DIAGNOSIS.md) in the video —
`seed_demo_data.py` (A->B->C) doesn't exercise it, because it only has
one piece of evidence per diagnosis.

Topology (fan-in, not linear like A->B->C): two independent datasets,
`inventory_recent` and `inventory_legacy`, feed directly into the same
target `logistics_report` — same hop (1), same evidence type
(`stale_data`), even the same base weight (0.5). The only difference is
WHEN they went stale:

  - inventory_recent: stopped updating ~30h ago (just crossed the 24h
    staleness threshold — "just broke").
  - inventory_legacy: hasn't updated in ~800h (~33 days) — chronically
    stale, likely a low-priority dataset nobody prioritizes, not an
    active incident.

Without the lag-aware mechanism, both would weigh exactly the same (0.5)
and `ranked_candidates` would show them tied. With recency decay,
`inventory_recent` should rank well above `inventory_legacy` — that
contrast is the point of the demo.

Usage:
    python3 scripts/seed_lag_aware_demo.py

After running it:
    python3 main.py diagnose "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.logistics_report,PROD)"

Note: same as seed_demo_data.py, DataHub's graph/search indexing is
asynchronous — if the traversal doesn't find the lineage right away,
wait a few seconds and retry.
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

_RECENT_STALE_HOURS = 30  # just crossed the 24h threshold
_LEGACY_STALE_HOURS = 800  # ~33 days, chronically stale


def _audit_stamp() -> AuditStampClass:
    return AuditStampClass(time=int(time.time() * 1000), actor=_ACTOR)


def _hours_ago_millis(hours: float) -> int:
    return int(time.time() * 1000 - hours * 3600 * 1000)


def _emit(client: DataHubClient, urn: str, aspect) -> None:
    mcp = MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect)
    client.graph.emit_mcp(mcp)
    logger.info("  OK: %s -> %s", type(aspect).__name__, urn)


def seed(client: DataHubClient) -> None:
    print("1/3 - Creating inventory_recent (stale for ~30h) and inventory_legacy (stale for ~33 days)...")
    _emit(client, URN_RECENT, DatasetPropertiesClass(
        name="inventory_recent",
        description="[Majestic demo] Just went stale — signal of an active incident.",
        lastModified=TimeStampClass(time=_hours_ago_millis(_RECENT_STALE_HOURS)),
    ))
    _emit(client, URN_RECENT, StatusClass(removed=False))
    _emit(client, URN_RECENT, OwnershipClass(
        owners=[OwnerClass(owner=_ACTOR, type=OwnershipTypeClass.TECHNICAL_OWNER)]
    ))

    _emit(client, URN_LEGACY, DatasetPropertiesClass(
        name="inventory_legacy",
        description="[Majestic demo] Chronically stale — same evidence type as inventory_recent, but much older.",
        lastModified=TimeStampClass(time=_hours_ago_millis(_LEGACY_STALE_HOURS)),
    ))
    _emit(client, URN_LEGACY, StatusClass(removed=False))
    _emit(client, URN_LEGACY, OwnershipClass(
        owners=[OwnerClass(owner=_ACTOR, type=OwnershipTypeClass.TECHNICAL_OWNER)]
    ))

    _emit(client, URN_TARGET, DatasetPropertiesClass(
        name="logistics_report",
        description="[Majestic demo] Target of the lag-aware scenario — two candidate causes at the same hop.",
    ))
    _emit(client, URN_TARGET, StatusClass(removed=False))
    _emit(client, URN_TARGET, OwnershipClass(
        owners=[OwnerClass(owner=_ACTOR, type=OwnershipTypeClass.TECHNICAL_OWNER)]
    ))

    print("2/3 - Chaining lineage: inventory_recent + inventory_legacy -> logistics_report (fan-in, same hop)...")
    _emit(client, URN_TARGET, UpstreamLineageClass(upstreams=[
        UpstreamClass(dataset=URN_RECENT, type=DatasetLineageTypeClass.TRANSFORMED, auditStamp=_audit_stamp()),
        UpstreamClass(dataset=URN_LEGACY, type=DatasetLineageTypeClass.TRANSFORMED, auditStamp=_audit_stamp()),
    ]))

    print("3/3 - Creating a dashboard downstream of logistics_report...")
    _emit(client, DASHBOARD_URN, DashboardInfoClass(
        title="[Majestic demo] Logistics Dashboard",
        description="Synthetic dashboard for the lag-aware scenario.",
        lastModified=ChangeAuditStampsClass(created=_audit_stamp(), lastModified=_audit_stamp()),
        datasets=[URN_TARGET],
    ))


def main() -> None:
    client = DataHubClient()
    if not client.is_connected:
        print("Could not connect. Run: datahub docker quickstart")
        sys.exit(1)

    print("Seeding Majestic's lag-aware scenario...\n")
    seed(client)

    print(
        "\nScenario seeded. Diagnosing logistics_report should return 2 ranked "
        "candidates with the same evidence_type (stale_data) and the same base "
        "weight (0.5) — but inventory_recent (~30h stale) should rank well above "
        "inventory_legacy (~800h stale) thanks to recency decay:"
    )
    print(f"   inventory_recent (recent) {URN_RECENT}")
    print(f"   inventory_legacy (chronic) {URN_LEGACY}")
    print(f"   logistics_report (target)  {URN_TARGET}")
    print(f"\nTry it with:")
    print(f'  python3 main.py diagnose "{URN_TARGET}"')
    print(
        "\nIf the traversal doesn't find the lineage right away, wait a few "
        "seconds (DataHub's graph/search indexing is asynchronous) and retry."
    )


if __name__ == "__main__":
    main()
