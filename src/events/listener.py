"""
"Lite" incident listener — polling version, not Kafka.

DataHub publishes every graph change to Kafka in real time (Metadata
Change Log). This module does NOT connect to that stream — it polls
DataHub's REST API periodically (via the same `DataHubGraph` the rest of
the project uses, not a raw HTTP call) looking for datasets with an
incident tag that haven't been seen yet, and runs the full diagnosis
pipeline (`MajesticAgent.diagnose`, which internally uses
`RootCauseDiagnoser`) on each one as soon as it appears.

It's deliberately the simple version: no Kafka, no persistence across
restarts (the set of already-processed URNs lives only in memory — if the
process restarts, it re-diagnoses whatever was already tagged). Enough to
demonstrate the pattern ("Majestic doesn't wait to be asked") without the
operational complexity of a real Kafka consumer.

Usage:
    python3 -m src.events.listener              # infinite loop, polls
                                                  # every LISTENER_POLL_INTERVAL_SECONDS
    python3 -m src.events.listener --once        # a single cycle (for tests/CI)
    python3 -m src.events.listener --interval 2  # interval override
"""

import argparse
import logging
import time
from typing import Dict, Optional, Set

from config.settings import INCIDENT_TAG_KEYWORDS, LISTENER_POLL_INTERVAL_SECONDS
from src.core.agent import MajesticAgent
from src.core.diagnoser import RootCauseDiagnoser
from src.graph.client import DataHubClient

logger = logging.getLogger(__name__)


class IncidentListener:
    """
    Detects new datasets with an incident tag and triggers the full
    diagnosis on each one, exactly once per URN.
    """

    def __init__(self, client: DataHubClient, poll_interval_seconds: Optional[float] = None):
        if not client.is_connected:
            raise RuntimeError("DataHubClient is not connected.")
        self.client = client
        self.poll_interval_seconds = poll_interval_seconds or LISTENER_POLL_INTERVAL_SECONDS
        # Reuses the SAME "does this tag count as an incident?" logic
        # already used by the normal diagnosis (diagnoser.py), instead of
        # reimplementing the check here and risking the two copies
        # drifting apart over time.
        self._diagnoser = RootCauseDiagnoser(client)
        self._agent = MajesticAgent(client)
        self._seen_urns: Set[str] = set()

    def poll_once(self) -> int:
        """
        A single cycle: looks for candidates, diagnoses the new ones.
        Returns: how many new incidents were processed in this cycle.
        """
        candidate_urns = self._find_candidate_urns()
        new_urns = sorted(candidate_urns - self._seen_urns)

        processed = 0
        for urn in new_urns:
            self._seen_urns.add(urn)

            # The free-text search can bring false positives (the word
            # "incident" in a description, not a tag) — confirm with the
            # same real check before diagnosing.
            evidence = self._diagnoser._check_incident_tags(urn)
            if not evidence:
                logger.debug(
                    "%s matched the text search but has no real incident "
                    "tag — discarding.",
                    urn,
                )
                continue

            self._handle_new_incident(urn, evidence)
            processed += 1

        return processed

    def run(self, once: bool = False) -> None:
        logger.info(
            "Incident listener started (polling every %ss, %s)",
            self.poll_interval_seconds,
            "single cycle" if once else "continuous loop",
        )
        while True:
            try:
                self.poll_once()
            except Exception:
                logger.exception("Error during the polling cycle — will retry next cycle.")

            if once:
                return
            time.sleep(self.poll_interval_seconds)

    def _find_candidate_urns(self) -> Set[str]:
        """
        Free-text search (same mechanism as DiagnosisWriter's Plan B in
        `_search_by_pattern_signature`, already validated against a real
        instance) for every incident keyword, merged into a single
        candidate set.
        """
        candidates: Set[str] = set()
        for keyword in INCIDENT_TAG_KEYWORDS:
            try:
                candidates.update(
                    self.client.graph.get_urns_by_filter(entity_types=["dataset"], query=keyword)
                )
            except Exception as exc:
                logger.warning("Search for keyword '%s' failed: %s", keyword, exc)
        return candidates

    def _handle_new_incident(self, urn: str, evidence: Dict) -> None:
        print(f"\nNew incident detected: {urn}")
        print(f"   {evidence['evidence']}")

        report = self._agent.diagnose(urn)
        print("Automatic diagnosis:")
        print(f"   Root cause: {report['root_cause_urn'] or '(no upstream evidence)'}")
        print(f"   Reason: {report['reason']}")
        print(f"   Confidence: {report['confidence'] * 100:.0f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="Majestic incident listener (polling, not Kafka).")
    parser.add_argument(
        "--once", action="store_true", help="Runs a single polling cycle and exits (useful for tests)."
    )
    parser.add_argument(
        "--interval", type=float, default=None, help="Seconds between cycles (default: LISTENER_POLL_INTERVAL_SECONDS)."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    client = DataHubClient()
    if not client.is_connected:
        print("Could not connect to DataHub. Run: datahub docker quickstart")
        raise SystemExit(1)

    listener = IncidentListener(client, poll_interval_seconds=args.interval)
    listener.run(once=args.once)


if __name__ == "__main__":
    main()
