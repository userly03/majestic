"""
Majestic CLI entrypoint.

Usage:
    python3 main.py [--quiet] diagnose <urn> [--write] [--business-context "text"] [--explain]
    python3 main.py [--quiet] impact <urn>
    python3 main.py doctor
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import requests

from src.core.agent import MajesticAgent
from src.core.narrator import explain
from src.graph.client import DataHubClient
from src.impact.risk_assessor import RiskAssessor
from src.impact.simulator import ImpactSimulator
from src.memory.writer import DiagnosisWriter

logger = logging.getLogger(__name__)

MEMORY_PROPERTY_YAML = str(
    Path(__file__).resolve().parent / "config" / "agent_memory_property.yaml"
)
DOCTOR_TEST_URN = "urn:li:dataset:(urn:li:dataPlatform:hive,_majestic_doctor_check,PROD)"
_DOCTOR_REPORT = {
    "pattern_signature": "doctor_check:0:0:0",
    "reason": "`main.py doctor` check — not a real diagnosis.",
    "confidence": 0.0,
}


def cmd_diagnose(
    client: DataHubClient, urn: str, write: bool, business_context: str, explain_flag: bool
) -> None:
    agent = MajesticAgent(client)
    writer = DiagnosisWriter(client)

    report = agent.diagnose(urn)

    previous = writer.find_previous_diagnosis(
        report["pattern_signature"], exclude_urn=urn
    )
    if previous:
        print("\nA diagnosis with this pattern signature already exists on another entity:")
        print(json.dumps(previous, indent=2, ensure_ascii=False))
        print(
            "   Note: this is a STRUCTURAL match (evidence type, hop, lineage "
            "counts, platform) — not confirmation that it's the same real "
            "incident. Review before trusting it blindly, especially if the "
            "business domain looks different."
        )

    print("\nDiagnosis:")
    print(json.dumps(report, indent=2, ensure_ascii=False))

    ranked = report.get("ranked_candidates") or []
    if len(ranked) > 1:
        print(f"\n{len(ranked)} root-cause candidates, ranked (lag-aware mechanism):")
        for i, candidate in enumerate(ranked, start=1):
            print(
                f"   {i}. {candidate['urn']} (hop {candidate['hop']}, "
                f"{candidate['evidence_type']}, score {candidate['adjusted_weight']:.2f})"
            )

    if explain_flag:
        print("\nExplanation:")
        print(explain(report))

    if write:
        ok = writer.write_report(urn, report, business_context=business_context)
        print("\nWrite-back:", "OK" if ok else "FAILED")


def cmd_impact(client: DataHubClient, urn: str) -> None:
    simulator = ImpactSimulator(client)
    impact_report = simulator.simulate(urn)
    print("\nImpact simulation:")
    print(json.dumps(impact_report, indent=2, ensure_ascii=False))


def cmd_check_change(client: DataHubClient, urn: str) -> None:
    """
    Evaluates whether a change on `urn` is safe to apply, combining the
    blast radius (ImpactSimulator, unmodified) with how orphaned the
    downstream is (RiskAssessor). Exits with code 1 if the risk exceeds
    the configured threshold (blocked) or 0 if it's approved — meant to
    be used as a gate in a CI/CD pipeline, not just for human reading.
    """
    simulator = ImpactSimulator(client)
    assessor = RiskAssessor(client)

    impact_report = simulator.simulate(urn)
    assessment = assessor.assess(urn, impact_report)

    print(f"\ncheck-change — {urn}")
    print(f"   Datasets affected downstream:   {impact_report['affected_datasets']}")
    print(f"   Dashboards affected downstream: {impact_report['affected_dashboards']}")
    print(f"   Downstream health (has owner):  {assessment['health_score'] * 100:.0f}%")
    print(f"   Risk level: {assessment['risk_label']} (score {assessment['risk_score']:.2f}, threshold {assessment['threshold']:.2f})")

    if assessment["should_block"]:
        print("\nChange blocked — high risk")
        sys.exit(1)
    else:
        print("\nChange is safe")
        sys.exit(0)


def _doctor_check_properties(client: DataHubClient) -> bool:
    """Confirms the structured properties from config/agent_memory_property.yaml
    are registered in DataHub; registers them if missing."""
    from datahub.api.entities.structuredproperties.structuredproperties import (
        StructuredProperties,
    )
    from datahub.metadata.schema_classes import StructuredPropertyDefinitionClass

    definitions = StructuredProperties.from_yaml(MEMORY_PROPERTY_YAML)

    def _missing():
        return [
            d
            for d in definitions
            if client.graph.get_aspect(d.urn, StructuredPropertyDefinitionClass) is None
        ]

    missing = _missing()
    if not missing:
        print("  OK: all 5 structured properties are already registered.")
        return True

    print(
        f"  WARNING: {len(missing)}/{len(definitions)} missing — registering from "
        f"{MEMORY_PROPERTY_YAML}..."
    )
    try:
        StructuredProperties.create(MEMORY_PROPERTY_YAML, client.graph)
    except Exception as exc:
        print(f"  FAILED: could not register: {exc}")
        return False

    still_missing = _missing()
    if still_missing:
        print(f"  FAILED: still missing: {[d.id for d in still_missing]}")
        return False

    print("  OK: registered successfully.")
    return True


def _doctor_check_write_read_cycle(client: DataHubClient) -> bool:
    """Quick write + read cycle against a dedicated test URN, to confirm
    write permissions without touching real data."""
    from datahub.emitter.mcp import MetadataChangeProposalWrapper
    from datahub.metadata.schema_classes import DatasetPropertiesClass, StatusClass

    # Ensures the test URN exists as an entity before applying the
    # structuredProperties patch (a PATCH on a nonexistent entity can fail).
    client.graph.emit_mcp(
        MetadataChangeProposalWrapper(
            entityUrn=DOCTOR_TEST_URN,
            aspect=DatasetPropertiesClass(
                name="_majestic_doctor_check",
                description="Test entity for `main.py doctor`. Safe to ignore/delete.",
            ),
        )
    )
    client.graph.emit_mcp(
        MetadataChangeProposalWrapper(entityUrn=DOCTOR_TEST_URN, aspect=StatusClass(removed=False))
    )

    writer = DiagnosisWriter(client)
    if not writer.write_report(DOCTOR_TEST_URN, _DOCTOR_REPORT):
        print("  FAILED: write failed.")
        return False

    read_back = writer.read_diagnosis(DOCTOR_TEST_URN)
    if read_back and read_back["pattern_signature"] == _DOCTOR_REPORT["pattern_signature"]:
        print("  OK: write and read confirmed.")
        return True

    print(f"  FAILED: what was read doesn't match what was written: {read_back}")
    return False


def cmd_doctor() -> None:
    """Runs, in a single command, what used to be 3 manual steps
    (scripts/spike_test.py + datahub properties upsert + scripts/spike_writeback_test.py)."""
    print("Majestic doctor — validating the setup before the demo\n")
    results: dict[str, bool] = {}

    print("1/3 — DataHub connection...")
    client = DataHubClient()
    results["DataHub connection"] = client.is_connected
    print("  OK: connected" if client.is_connected else "  FAILED: could not connect")

    if client.is_connected:
        print("\n2/3 — Structured properties registered...")
        try:
            results["Structured properties registered"] = _doctor_check_properties(client)
        except Exception as exc:
            print(f"  FAILED: error checking properties: {exc}")
            results["Structured properties registered"] = False

        print("\n3/3 — Write/read cycle...")
        try:
            results["Write/read cycle"] = _doctor_check_write_read_cycle(client)
        except Exception as exc:
            print(f"  FAILED: error during the write/read cycle: {exc}")
            results["Write/read cycle"] = False
    else:
        print("\n2/3 and 3/3 — Skipped (no connection).")
        results["Structured properties registered"] = False
        results["Write/read cycle"] = False

    print("\n" + "=" * 50)
    print("Summary:")
    for name, ok in results.items():
        print(f"  {'OK' if ok else 'FAILED'}: {name}")

    all_ok = all(results.values())
    if all_ok:
        print("\nEverything is ready for the demo.")
    else:
        print("\nThere are pending steps before the demo — check the FAILED items above.")
        if not results["DataHub connection"]:
            print("   Run: datahub docker quickstart")

    sys.exit(0 if all_ok else 1)


def _human_error(exc: Exception) -> str:
    """Translates typical SDK/network exceptions into a readable message for
    the demo, instead of letting a raw traceback print."""
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return "Could not connect to DataHub (host unreachable or timeout). Run: datahub docker quickstart"

    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        if status == 404:
            return "Dataset not found in DataHub. Check that the URN is correct."
        if status == 400:
            return "DataHub rejected the URN as invalid. Check that it's a complete URN (e.g. 'urn:li:dataset:(...)')."
        return f"DataHub responded with HTTP error {status}."

    if isinstance(exc, RuntimeError):
        return str(exc)

    return f"Unexpected error ({type(exc).__name__}): {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Majestic — data lineage and observability agent.")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=(
            "Suppresses internal logs (connection, traversal, etc.) and leaves only "
            "the final result — meant for screen-sharing during a demo."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    diagnose_parser = subparsers.add_parser("diagnose", help="Diagnoses the root cause of a URN.")
    diagnose_parser.add_argument("urn", help="URN of the dataset to diagnose.")
    diagnose_parser.add_argument(
        "--write", action="store_true", help="Persists the diagnosis in DataHub."
    )
    diagnose_parser.add_argument(
        "--business-context",
        default=None,
        help="Business context / lesson learned to save alongside the diagnosis.",
    )
    diagnose_parser.add_argument(
        "--explain",
        action="store_true",
        help=(
            "Writes up the evidence chain in natural language. Today it's a "
            "deterministic template (doesn't call any external LLM) — see "
            "src/core/narrator.py."
        ),
    )

    impact_parser = subparsers.add_parser("impact", help="Simulates the downstream impact of a change.")
    impact_parser.add_argument("urn", help="URN of the dataset to modify.")

    check_change_parser = subparsers.add_parser(
        "check-change",
        help="Evaluates whether a change on a dataset is safe (CI/CD gate): exit 0 approves, exit 1 blocks.",
    )
    check_change_parser.add_argument("--urn", required=True, help="URN of the dataset to evaluate.")
    check_change_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Has no effect today — check-change never writes anything to DataHub "
            "(it only reads lineage and ownership). The flag is accepted for "
            "compatibility with CI pipelines that already pass it to other tools; "
            "reserved for if check-change ever applies the change instead of only "
            "evaluating it."
        ),
    )

    subparsers.add_parser(
        "doctor",
        help="Validates connection, structured properties, and write permissions in a single command.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    if args.command == "doctor":
        cmd_doctor()
        return

    client = DataHubClient()
    if not client.is_connected:
        logger.error("Could not connect to DataHub. Run: datahub docker quickstart")
        sys.exit(1)

    try:
        if args.command == "diagnose":
            cmd_diagnose(client, args.urn, args.write, args.business_context, args.explain)
        elif args.command == "impact":
            cmd_impact(client, args.urn)
        elif args.command == "check-change":
            cmd_check_change(client, args.urn)
    except Exception as exc:
        logger.debug("Full error detail", exc_info=True)
        print(f"\nError: {_human_error(exc)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
