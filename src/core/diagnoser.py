"""
Root-cause diagnosis engine.
Walks the upstream lineage nodes, hop by hop, looking for concrete
evidence in the graph (never speculation): incident tags, datasets with
no owner, stale data, or recently modified schemas.

The causal chain extends as long as there's evidence at each hop and
stops as soon as a hop contributes none (or upon reaching
MAX_CAUSAL_LINKS). The root cause is the farthest evidenced link: it's
the one that, following the project's "blind detective" pattern, tends to
be several hops upstream of the original symptom.
"""

import logging
import time as time_module
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple, Type

from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlobalTagsClass,
    OwnershipClass,
    SchemaMetadataClass,
)

from config.settings import (
    EVIDENCE_WEIGHT_INCIDENT_TAG,
    EVIDENCE_WEIGHT_SCHEMA_CHANGE,
    EVIDENCE_WEIGHT_STALE_DATA,
    EVIDENCE_WEIGHT_UNOWNED,
    FRESHNESS_THRESHOLD_HOURS,
    INCIDENT_TAG_KEYWORDS,
    LAG_DECAY_HALFLIFE_HOURS,
    MAX_CAUSAL_LINKS,
    MAX_PARALLEL_REQUESTS,
    RANKED_CANDIDATES_TOP_K,
    UPSTREAM_INHERITANCE_DISCOUNT,
)
from src.graph.client import DataHubClient

logger = logging.getLogger(__name__)

# Relative weight of each evidence type: the higher the weight, the more
# determinant it's considered when pointing at the root cause.
#
# IMPORTANT — this is a reasoned ranking, not a statistical calibration:
# there is no (yet) dataset of real resolved incidents to tune these
# numbers against, and this project is explicit about not faking a
# precision that wasn't measured (the same standard the project already
# applies to not inventing an "80% chance of failure in 48h" without
# historical data). What CAN be defended is the relative ORDER, by
# specificity and causal strength of the signal:
#
#   incident_tag (0.9)   — an explicit signal set by a human; it's the
#                          most direct possible statement of "this is the
#                          cause," even though the agent itself didn't
#                          generate it.
#   schema_change (0.7)  — a real structural change with a timestamp;
#                          strong, but circumstantial (coincides in time,
#                          doesn't prove causation).
#   stale_data (0.5)     — absence of an update; could be a downed ETL,
#                          but could also be a weekend or a source that
#                          legitimately updates rarely. Weaker signal,
#                          more false positives.
#   unowned (0.3)        — the weakest: not having an owner doesn't break
#                          a pipeline by itself, it only makes it harder
#                          to escalate once something else has already
#                          broken.
#
# The absolute defaults (0.9/0.7/0.5/0.3) aren't calibrated against a
# real incident dataset — that's why they're configurable via
# config/settings.py (MAJESTIC_EVIDENCE_WEIGHT_*), not fixed constants
# here. A team with a real incident history can recalibrate them without
# touching this file. See "Technical notes" in README.md.
_EVIDENCE_WEIGHTS = {
    "incident_tag": EVIDENCE_WEIGHT_INCIDENT_TAG,
    "schema_change": EVIDENCE_WEIGHT_SCHEMA_CHANGE,
    "stale_data": EVIDENCE_WEIGHT_STALE_DATA,
    "unowned": EVIDENCE_WEIGHT_UNOWNED,
}


class RootCauseDiagnoser:
    """Analyzes lineage nodes and determines the root cause with traceable evidence."""

    def __init__(self, client: DataHubClient):
        if not client.is_connected:
            raise RuntimeError("DataHubClient is not connected. Aborting diagnosis.")
        self.client = client
        # Per-instance get_aspect cache: the same (urn, aspect type) isn't
        # requested twice while this RootCauseDiagnoser is alive. No race
        # condition risk between parallel hops because the BFS that builds
        # upstream_nodes already deduplicates URNs (visited set in
        # traversal.py).
        self._aspect_cache: Dict[Tuple[str, type], Any] = {}

    def analyze(self, upstream_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Given a list of upstream nodes (with 'urn' and 'hop'), returns the
        diagnosis: root cause, evidenced causal chain, and confidence.
        """
        logger.info("Analyzing %d upstream nodes...", len(upstream_nodes))

        nodes_by_hop: Dict[int, List[str]] = {}
        for node in upstream_nodes:
            nodes_by_hop.setdefault(node["hop"], []).append(node["urn"])

        causal_chain: List[Dict[str, Any]] = []
        for hop in sorted(nodes_by_hop):
            if len(causal_chain) >= MAX_CAUSAL_LINKS:
                break

            urns_at_hop = nodes_by_hop[hop]
            evidences = self._collect_evidence_parallel(urns_at_hop)
            hop_evidence = [
                {"urn": urn, "hop": hop, **evidence}
                for urn, evidence in zip(urns_at_hop, evidences)
                if evidence is not None
            ]
            if not hop_evidence:
                logger.info("No evidence at hop %d, the chain stops there.", hop)
                break

            causal_chain.extend(hop_evidence)

        if not causal_chain:
            return {
                "root_cause_urn": None,
                "reason": "No concrete evidence found in the upstream graph.",
                "causal_chain": [],
                "confidence": 0.0,
                "ranked_candidates": [],
            }

        self._apply_adjusted_weights(causal_chain)

        root_link = max(causal_chain, key=lambda link: (link["hop"], link["adjusted_weight"]))
        ranked_candidates = sorted(
            causal_chain, key=lambda link: (link["hop"], link["adjusted_weight"]), reverse=True
        )[:RANKED_CANDIDATES_TOP_K]

        return {
            "root_cause_urn": root_link["urn"],
            "reason": self._explain(root_link),
            "causal_chain": causal_chain,
            "confidence": self._confidence(causal_chain),
            "ranked_candidates": ranked_candidates,
        }

    def _collect_evidence_parallel(self, urns: List[str]) -> List[Optional[Dict[str, Any]]]:
        """
        Runs _collect_evidence for every URN in a given hop in parallel
        (up to MAX_PARALLEL_REQUESTS at a time) instead of one by one.
        With a single node per hop (the common case) it's equivalent to
        the sequential version; the benefit shows up on nodes with wide
        fan-in. Returns results in the same order as `urns`.
        """
        if len(urns) <= 1:
            return [self._collect_evidence(urn) for urn in urns]

        with ThreadPoolExecutor(max_workers=min(len(urns), MAX_PARALLEL_REQUESTS)) as pool:
            return list(pool.map(self._collect_evidence, urns))

    def _get_aspect_cached(self, urn: str, aspect_type: Type) -> Any:
        key = (urn, aspect_type)
        if key not in self._aspect_cache:
            self._aspect_cache[key] = self.client.graph.get_aspect(urn, aspect_type)
        return self._aspect_cache[key]

    def _collect_evidence(self, urn: str) -> Optional[Dict[str, Any]]:
        """Looks for concrete evidence (tag, owner, freshness, schema) on a URN."""
        tag_evidence = self._check_incident_tags(urn)
        if tag_evidence:
            return tag_evidence

        schema_evidence = self._check_recent_schema_change(urn)
        if schema_evidence:
            return schema_evidence

        freshness_evidence = self._check_staleness(urn)
        if freshness_evidence:
            return freshness_evidence

        ownership_evidence = self._check_ownership(urn)
        if ownership_evidence:
            return ownership_evidence

        return None

    def _check_incident_tags(self, urn: str) -> Optional[Dict[str, Any]]:
        tags = self._get_aspect_cached(urn, GlobalTagsClass)
        if not tags:
            return None
        for assoc in tags.tags:
            tag_lower = assoc.tag.lower()
            for keyword in INCIDENT_TAG_KEYWORDS:
                if keyword in tag_lower:
                    return {
                        "evidence_type": "incident_tag",
                        "evidence": f"tag '{assoc.tag}' matches incident keyword '{keyword}'",
                        "weight": _EVIDENCE_WEIGHTS["incident_tag"],
                    }
        return None

    def _check_recent_schema_change(self, urn: str) -> Optional[Dict[str, Any]]:
        schema = self._get_aspect_cached(urn, SchemaMetadataClass)
        if not schema or not schema.lastModified:
            return None
        age_hours = self._hours_since(schema.lastModified.time)
        if age_hours is not None and age_hours <= FRESHNESS_THRESHOLD_HOURS:
            return {
                "evidence_type": "schema_change",
                "evidence": f"schema modified {age_hours:.1f}h ago (threshold {FRESHNESS_THRESHOLD_HOURS}h)",
                "weight": _EVIDENCE_WEIGHTS["schema_change"],
                "age_hours": age_hours,
            }
        return None

    def _check_staleness(self, urn: str) -> Optional[Dict[str, Any]]:
        props = self._get_aspect_cached(urn, DatasetPropertiesClass)
        if not props or not props.lastModified:
            return None
        age_hours = self._hours_since(props.lastModified.time)
        if age_hours is not None and age_hours > FRESHNESS_THRESHOLD_HOURS:
            return {
                "evidence_type": "stale_data",
                "evidence": f"not updated for {age_hours:.1f}h (threshold {FRESHNESS_THRESHOLD_HOURS}h)",
                "weight": _EVIDENCE_WEIGHTS["stale_data"],
                "age_hours": age_hours,
            }
        return None

    def _check_ownership(self, urn: str) -> Optional[Dict[str, Any]]:
        ownership = self._get_aspect_cached(urn, OwnershipClass)
        if ownership is not None and not ownership.owners:
            return {
                "evidence_type": "unowned",
                "evidence": "dataset has no assigned owner",
                "weight": _EVIDENCE_WEIGHTS["unowned"],
            }
        return None

    @staticmethod
    def _hours_since(epoch_millis: int) -> Optional[float]:
        if not epoch_millis:
            return None
        now_millis = time_module.time() * 1000
        return (now_millis - epoch_millis) / (1000 * 60 * 60)

    @staticmethod
    def _explain(link: Dict[str, Any]) -> str:
        return f"{link['urn']} (hop {link['hop']}): {link['evidence']}"

    @staticmethod
    def _recency_decay(age_hours: Optional[float]) -> float:
        """
        Exponential recency decay — see docs/LAG_AWARE_DIAGNOSIS.md.
        Evidence with `age_hours=0` (just occurred) isn't discounted; as
        time passes the weight decays toward 0 without ever reaching
        exact zero. Without `age_hours` (incident_tag, unowned: no
        reliable timestamp available) there's no decay — returns 1.0.
        """
        if age_hours is None:
            return 1.0
        return 0.5 ** (max(age_hours, 0.0) / LAG_DECAY_HALFLIFE_HOURS)

    @staticmethod
    def _apply_adjusted_weights(causal_chain: List[Dict[str, Any]]) -> None:
        """
        Computes `adjusted_weight` for every link in the chain, mutating
        `causal_chain` in place. Two adjustments on top of the base
        `weight` (which is NEVER modified, so it keeps being the
        evidence type's "catalog" weight):

        1. Recency decay (`_recency_decay`), only for evidence with
           `age_hours` available.
        2. Inheritance discount: if the same `evidence_type` appears at a
           farther hop (more upstream), the closer-to-target hop is
           likely inheriting the problem, not contributing an independent
           signal — multiplied by UPSTREAM_INHERITANCE_DISCOUNT.

        See docs/LAG_AWARE_DIAGNOSIS.md for the full reasoning.
        """
        for link in causal_chain:
            decay = RootCauseDiagnoser._recency_decay(link.get("age_hours"))
            link["adjusted_weight"] = round(link["weight"] * decay, 4)

        for link in causal_chain:
            inherited_from_further_upstream = any(
                other["evidence_type"] == link["evidence_type"] and other["hop"] > link["hop"]
                for other in causal_chain
            )
            if inherited_from_further_upstream:
                link["adjusted_weight"] = round(
                    link["adjusted_weight"] * UPSTREAM_INHERITANCE_DISCOUNT, 4
                )

    @staticmethod
    def _confidence(causal_chain: List[Dict[str, Any]]) -> float:
        """
        Confidence heuristic: average of the ADJUSTED weight (decay +
        inheritance discount) across the chain, with a small bonus per
        additional confirmed link. Not a calibrated probability — still
        needs validation against real incidents.
        """
        avg_weight = sum(link["adjusted_weight"] for link in causal_chain) / len(causal_chain)
        chain_bonus = min(0.1 * (len(causal_chain) - 1), 0.2)
        return round(min(avg_weight + chain_bonus, 1.0), 2)
