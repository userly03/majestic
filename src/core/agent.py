"""
Majestic's main agent.
Takes an alert or a problematic URN, diagnoses the root cause, and
returns a structured report along with the pattern signature that
Phase 3 (memory) uses to recognize the same case on another entity.
"""

import logging
import re
from typing import Any, Dict, Optional

from config.settings import DEFAULT_MAX_HOPS
from src.core.diagnoser import RootCauseDiagnoser
from src.graph.client import DataHubClient
from src.graph.traversal import LineageTraversal

logger = logging.getLogger(__name__)

_PLATFORM_RE = re.compile(r"urn:li:dataPlatform:([^,]+)")


class MajesticAgent:
    """Main orchestrator of the root-cause diagnosis pipeline."""

    def __init__(self, client: DataHubClient):
        self.client = client
        self.traversal = LineageTraversal(client)
        self.diagnoser = RootCauseDiagnoser(client)
        logger.info("Majestic agent initialized")

    def diagnose(self, urn: str) -> Dict[str, Any]:
        """
        Runs the full diagnosis pipeline for a given URN.

        Steps:
            1. Walk upstream (and downstream, for the structural signature).
            2. Cross-reference owners, schemas, and tags looking for real
               evidence (Phase 2).
            3. Return the report; persisting it to the graph is
               DiagnosisWriter's responsibility (Phase 3), not this
               method's.
        """
        logger.info("Starting diagnosis for: %s", urn)

        upstream_nodes = self.traversal.get_upstream(urn, max_hops=DEFAULT_MAX_HOPS)
        downstream_nodes = self.traversal.get_downstream(urn, max_hops=DEFAULT_MAX_HOPS)

        diagnosis = self.diagnoser.analyze(upstream_nodes)

        report = {
            "target_urn": urn,
            "upstream_count": len(upstream_nodes),
            "downstream_count": len(downstream_nodes),
            "root_cause_urn": diagnosis["root_cause_urn"],
            "reason": diagnosis["reason"],
            "causal_chain": diagnosis["causal_chain"],
            "confidence": diagnosis["confidence"],
            "ranked_candidates": diagnosis["ranked_candidates"],
            "pattern_signature": self._build_pattern_signature(
                diagnosis, len(upstream_nodes), len(downstream_nodes), urn
            ),
        }

        logger.info("Diagnosis complete: %s", report)
        return report

    @staticmethod
    def _extract_platform(urn: Optional[str]) -> str:
        """Extracts the platform ('hive', 'snowflake', ...) from a DataHub URN."""
        if not urn:
            return "unknown"
        match = _PLATFORM_RE.search(urn)
        return match.group(1) if match else "unknown"

    @staticmethod
    def _build_pattern_signature(
        diagnosis: Dict[str, Any],
        upstream_count: int,
        downstream_count: int,
        target_urn: str,
    ) -> str:
        """
        Deterministic 'anomaly_type:depth:upstream:downstream:platform'
        signature (see Phase 3 in docs/PITCH.md). Lets Majestic recognize
        the same causal structure on another entity without reasoning
        from scratch.

        The platform component was added (2026-08-08, see
        docs/AUDIT_REPORT.md Section 1.4 and Section 2 item 1) because the
        signature without it is too coarse: two completely unrelated
        datasets in different domains, with the same evidence_type/hop/
        upstream/downstream, produced the same signature. Anchoring to the
        causal node's platform is a cheap improvement (the data already
        comes from the URN, no extra DataHub call) but a PARTIAL one: two
        datasets from the same business domain but different platforms no
        longer collide, but two datasets from different domains on the
        SAME platform still can. That's why `find_previous_diagnosis`
        (src/memory/writer.py) and the reuse message in `main.py` always
        treat a match as "same structure," never as "confirmed same
        incident" — see the note in cmd_diagnose.
        """
        causal_chain = diagnosis["causal_chain"]
        if not causal_chain:
            platform = MajesticAgent._extract_platform(target_urn)
            return f"unknown:0:{upstream_count}:{downstream_count}:{platform}"

        root_urn = diagnosis["root_cause_urn"]
        root_link = next(link for link in causal_chain if link["urn"] == root_urn)
        platform = MajesticAgent._extract_platform(root_urn)
        return (
            f"{root_link['evidence_type']}:{root_link['hop']}:"
            f"{upstream_count}:{downstream_count}:{platform}"
        )
