"""
RiskAssessor — evaluates whether a proposed change to a dataset is safe
to apply, combining ImpactSimulator's `risk_level` (blast radius) with a
`health_score` of the downstream itself (what fraction of the affected
nodes has an assigned owner).

Doesn't replace or modify ImpactSimulator — it consumes it as-is (its
already-categorical `risk_level`) and adds a second, independent signal
ImpactSimulator doesn't compute: how much of the downstream is "adrift"
with nobody responsible. A change with a high blast radius but 100%
downstream ownership is safer to touch (there's someone to notify) than
one with the same blast radius but an unowned downstream (nobody finds
out until it's too late).
"""

import logging
from typing import Any, Dict, List

from datahub.metadata.schema_classes import OwnershipClass

from config.settings import CHECK_CHANGE_RISK_THRESHOLD, DEFAULT_MAX_HOPS
from src.graph.client import DataHubClient
from src.graph.traversal import LineageTraversal

logger = logging.getLogger(__name__)

# risk_level (from ImpactSimulator) -> base score, on the same 0-1 scale
# as health_score, so they can be combined. Same criterion as
# _EVIDENCE_WEIGHTS in diagnoser.py: defensible order, absolute values
# not calibrated against real incidents.
_RISK_LEVEL_SCORE = {"none": 0.0, "low": 0.33, "medium": 0.66, "high": 1.0}

# Relative weight of blast radius vs. downstream orphanhood when
# combining both signals into a single risk_score. Blast radius weighs
# more because a change that affects nobody is safe regardless of how
# "orphaned" the little downstream it has might be.
_BLAST_RADIUS_WEIGHT = 0.6
_ORPHANHOOD_WEIGHT = 0.4


class RiskAssessor:
    """Decides whether a change on a URN should be blocked before it's applied."""

    def __init__(self, client: DataHubClient):
        if not client.is_connected:
            raise RuntimeError("DataHubClient is not connected.")
        self.client = client
        self.traversal = LineageTraversal(client)

    def assess(self, urn: str, impact_report: Dict[str, Any]) -> Dict[str, Any]:
        """
        Combines `impact_report` (already computed by
        ImpactSimulator.simulate()) with the downstream's own
        health_score.

        Returns:
            Dict with health_score, risk_score (0-1), risk_label
            (LOW/MEDIUM/HIGH), and should_block (bool).
        """
        downstream_nodes = self.traversal.get_downstream(urn, max_hops=DEFAULT_MAX_HOPS)
        health_score = self._health_score(downstream_nodes)

        risk_level_score = _RISK_LEVEL_SCORE.get(impact_report["risk_level"], 0.0)
        orphanhood = 1.0 - health_score
        risk_score = round(
            _BLAST_RADIUS_WEIGHT * risk_level_score + _ORPHANHOOD_WEIGHT * orphanhood, 2
        )

        return {
            "urn": urn,
            "health_score": health_score,
            "risk_score": risk_score,
            "risk_label": self._risk_label(risk_score),
            "should_block": risk_score >= CHECK_CHANGE_RISK_THRESHOLD,
            "threshold": CHECK_CHANGE_RISK_THRESHOLD,
        }

    def _health_score(self, downstream_nodes: List[Dict[str, Any]]) -> float:
        """
        Fraction of downstream nodes WITH at least one assigned owner.
        1.0 = the whole downstream has an owner (healthy); 0.0 = none of
        it does (nobody finds out if this breaks). With no downstream,
        there's nothing at stake: a neutral health_score (1.0).
        """
        if not downstream_nodes:
            return 1.0

        owned = 0
        for node in downstream_nodes:
            ownership = self.client.graph.get_aspect(node["urn"], OwnershipClass)
            if ownership is not None and ownership.owners:
                owned += 1

        return round(owned / len(downstream_nodes), 2)

    @staticmethod
    def _risk_label(risk_score: float) -> str:
        if risk_score >= 0.67:
            return "HIGH"
        if risk_score >= 0.34:
            return "MEDIUM"
        return "LOW"
