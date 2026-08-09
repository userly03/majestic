"""
Synthetic data seeding for the Majestic demo.

Creates a guaranteed mini lineage graph: A -> B -> C, with a real anomaly
in B (no owner + incident tag) so that diagnosing C *always* finds a root
cause, without depending on `datahub docker quickstart`'s datapack having
something interesting by chance. Also creates a dashboard downstream of C
so `main.py impact` has something to count.

Usage:
    python3 scripts/seed_demo_data.py

After running it:
    python3 main.py diagnose "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)"
    python3 main.py impact   "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)"

Note: DataHub's graph/search indexing is asynchronous (via Kafka). If the
traversal doesn't find the lineage right after running this script, wait
a few seconds and retry.
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
    logger.info("  OK: %s -> %s", type(aspect).__name__, urn)


def seed(client: DataHubClient) -> None:
    print("1/4 - Creating datasets A (healthy) -> B (anomaly) -> C (target)...")
    _emit(client, URN_A, DatasetPropertiesClass(
        name="raw_marketing",
        description="[Majestic demo] Raw marketing data. Healthy node: has an owner, no incident tags.",
    ))
    _emit(client, URN_A, StatusClass(removed=False))
    _emit(client, URN_A, OwnershipClass(
        owners=[OwnerClass(owner=_ACTOR, type=OwnershipTypeClass.TECHNICAL_OWNER)]
    ))

    _emit(client, URN_B, DatasetPropertiesClass(
        name="marketing_etl",
        description="[Majestic demo] Intermediate ETL. This is where the anomaly lives: no owner and an incident tag, on purpose.",
    ))
    _emit(client, URN_B, StatusClass(removed=False))
    _emit(client, URN_B, OwnershipClass(owners=[]))  # anomaly: no owner, deliberate

    _emit(client, URN_C, DatasetPropertiesClass(
        name="sales_report",
        description="[Majestic demo] Sales report. This is the URN diagnosed in the demo.",
    ))
    _emit(client, URN_C, StatusClass(removed=False))
    _emit(client, URN_C, OwnershipClass(
        owners=[OwnerClass(owner=_ACTOR, type=OwnershipTypeClass.TECHNICAL_OWNER)]
    ))

    print("2/4 - Chaining lineage A -> B -> C...")
    _emit(client, URN_B, UpstreamLineageClass(upstreams=[
        UpstreamClass(dataset=URN_A, type=DatasetLineageTypeClass.TRANSFORMED, auditStamp=_audit_stamp())
    ]))
    _emit(client, URN_C, UpstreamLineageClass(upstreams=[
        UpstreamClass(dataset=URN_B, type=DatasetLineageTypeClass.TRANSFORMED, auditStamp=_audit_stamp())
    ]))

    print("3/4 - Marking the anomaly on B with an incident tag...")
    _emit(client, TAG_URN, TagPropertiesClass(
        name="Majestic Demo: Incident",
        description="Synthetic tag for the Majestic demo: marks a dataset under investigation for a data incident.",
    ))
    _emit(client, URN_B, GlobalTagsClass(tags=[TagAssociationClass(tag=TAG_URN)]))

    print("4/4 - Creating a dashboard downstream of C (for `main.py impact`)...")
    _emit(client, DASHBOARD_URN, DashboardInfoClass(
        title="[Majestic demo] Sales Dashboard",
        description="Synthetic dashboard consuming sales_report, so the impact simulator has something to count.",
        lastModified=ChangeAuditStampsClass(created=_audit_stamp(), lastModified=_audit_stamp()),
        datasets=[URN_C],
    ))


def main() -> None:
    client = DataHubClient()
    if not client.is_connected:
        print("Could not connect. Run: datahub docker quickstart")
        sys.exit(1)

    print("Seeding Majestic's demo graph...\n")
    seed(client)

    print("\nGraph seeded. Diagnosing C should find the root cause in B (hop 1, incident_tag):")
    print(f"   A (healthy)       {URN_A}")
    print(f"   B (anomaly)       {URN_B}")
    print(f"   C (target)        {URN_C}")
    print(f"   Dashboard         {DASHBOARD_URN}")
    print(f"\nTry it with:")
    print(f'  python3 main.py diagnose "{URN_C}"')
    print(f'  python3 main.py impact "{URN_C}"')
    print(
        "\nIf the traversal doesn't find the lineage right away, wait a few "
        "seconds (DataHub's graph/search indexing is asynchronous) and retry."
    )


if __name__ == "__main__":
    main()
