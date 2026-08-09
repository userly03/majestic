"""
Downstream impact simulator.
Before a critical change is applied to a dataset, walks the same
traversal the diagnosis uses (Phase 1) but downward, to estimate which
tables, dashboards, and owners would be affected.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from datahub.metadata.schema_classes import CorpUserInfoClass, OwnershipClass

from config.settings import DEFAULT_MAX_HOPS, MAX_PARALLEL_REQUESTS
from src.graph.client import DataHubClient
from src.graph.traversal import LineageTraversal

logger = logging.getLogger(__name__)

# Risk-heuristic thresholds: any affected dashboard is already "high"
# because it directly impacts business consumers; without dashboards,
# downstream dataset volume decides the level.
_HIGH_RISK_DATASET_THRESHOLD = 10
_MEDIUM_RISK_DATASET_THRESHOLD = 1


class ImpactSimulator:
    """Simulates the impact of a change by walking the downstream lineage."""

    def __init__(self, client: DataHubClient):
        if not client.is_connected:
            raise RuntimeError("DataHubClient is not connected.")
        self.client = client
        self.traversal = LineageTraversal(client)

    def simulate(self, urn: str) -> Dict[str, Any]:
        """
        Computes the downstream impact of a change on the given dataset.

        Returns:
            Dict with affected datasets, dashboards, and owners.
        """
        logger.info("Simulating downstream impact for: %s", urn)

        downstream_nodes = self.traversal.get_downstream(urn, max_hops=DEFAULT_MAX_HOPS)

        affected_dashboards = [
            node for node in downstream_nodes if node["entity_type"] == "dashboard"
        ]
        affected_owners = self._collect_owners(downstream_nodes)

        impact_report = {
            "source_urn": urn,
            "affected_datasets": len(downstream_nodes),
            "affected_dashboards": len(affected_dashboards),
            "affected_owners": affected_owners,
            "affected_owners_display": self._resolve_owner_names(affected_owners),
            "risk_level": self._risk_level(len(downstream_nodes), len(affected_dashboards)),
        }

        logger.info("Simulation complete: %s", impact_report)
        return impact_report

    def _collect_owners(self, downstream_nodes: List[Dict[str, Any]]) -> List[str]:
        urns = [node["urn"] for node in downstream_nodes]
        if not urns:
            return []

        # One get_aspect call per downstream node; in parallel so latency
        # doesn't grow linearly with how many consumers a dataset has.
        def fetch_ownership(urn: str):
            return self.client.graph.get_aspect(urn, OwnershipClass)

        if len(urns) == 1:
            ownerships = [fetch_ownership(urns[0])]
        else:
            with ThreadPoolExecutor(max_workers=min(len(urns), MAX_PARALLEL_REQUESTS)) as pool:
                ownerships = list(pool.map(fetch_ownership, urns))

        owners = set()
        for ownership in ownerships:
            if ownership:
                owners.update(owner.owner for owner in ownership.owners)
        return sorted(owners)

    def _resolve_owner_names(self, owner_urns: List[str]) -> List[Dict[str, str]]:
        """
        Resolves a readable name (`displayName`/`fullName` from
        `CorpUserInfoClass`) for each owner URN — so the demo/CLI shows
        "Sarah, from the Finance team" instead of
        `urn:li:corpuser:sarah.finance`. Never drops an owner just
        because its name couldn't be resolved: if `CorpUserInfoClass`
        doesn't exist or the read fails, it falls back to the raw URN.
        """
        if not owner_urns:
            return []

        def fetch_name(urn: str) -> Dict[str, str]:
            try:
                info = self.client.graph.get_aspect(urn, CorpUserInfoClass)
            except Exception:
                info = None
            display_name = (info.displayName or info.fullName) if info else None
            return {"urn": urn, "name": display_name or urn}

        if len(owner_urns) == 1:
            return [fetch_name(owner_urns[0])]

        with ThreadPoolExecutor(max_workers=min(len(owner_urns), MAX_PARALLEL_REQUESTS)) as pool:
            return list(pool.map(fetch_name, owner_urns))

    @staticmethod
    def _risk_level(affected_count: int, dashboard_count: int) -> str:
        if affected_count == 0:
            return "none"
        if dashboard_count > 0 or affected_count >= _HIGH_RISK_DATASET_THRESHOLD:
            return "high"
        if affected_count >= _MEDIUM_RISK_DATASET_THRESHOLD:
            return "medium"
        return "low"
