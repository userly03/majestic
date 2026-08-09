"""
Integration tests: run against a real DataHub instance, not mocks. Close
the gap unit tests (100% mocks) leave between "passes in CI" and "actually
works."

Skipped automatically unless explicitly opted into, so a local `pytest`
with no DataHub up stays instant:

    MAJESTIC_RUN_INTEGRATION_TESTS=1 pytest -m integration

`test_diagnose_seeded_graph_finds_root_cause_in_b` and
`test_impact_seeded_graph_finds_dashboard` additionally require having
run `python3 scripts/seed_demo_data.py` beforehand — if not, they skip
with a message explaining why (they don't fail: missing seeded data
isn't a code bug).
"""

import os

import pytest

from src.core.agent import MajesticAgent
from src.graph.client import DataHubClient
from src.impact.simulator import ImpactSimulator
from src.memory.writer import DiagnosisWriter

pytestmark = pytest.mark.integration

_INTEGRATION_TEST_URN = "urn:li:dataset:(urn:li:dataPlatform:hive,_majestic_integration_test,PROD)"
_URN_C = "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)"
_URN_B = "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.marketing_etl,PROD)"


@pytest.fixture(scope="module")
def live_client():
    if not os.getenv("MAJESTIC_RUN_INTEGRATION_TESTS"):
        pytest.skip(
            "Integration tests disabled by default. Run with "
            "MAJESTIC_RUN_INTEGRATION_TESTS=1 pytest -m integration"
        )

    client = DataHubClient()
    if not client.is_connected:
        pytest.skip(
            "No real DataHub instance available. "
            "Run: datahub docker quickstart"
        )
    return client


def test_write_then_read_diagnosis_round_trips(live_client):
    """Real write-back cycle: writes structuredProperties and reads them back."""
    from datahub.emitter.mcp import MetadataChangeProposalWrapper
    from datahub.metadata.schema_classes import DatasetPropertiesClass, StatusClass

    live_client.graph.emit_mcp(
        MetadataChangeProposalWrapper(
            entityUrn=_INTEGRATION_TEST_URN,
            aspect=DatasetPropertiesClass(
                name="_majestic_integration_test",
                description="Integration test entity. Safe to ignore/delete.",
            ),
        )
    )
    live_client.graph.emit_mcp(
        MetadataChangeProposalWrapper(entityUrn=_INTEGRATION_TEST_URN, aspect=StatusClass(removed=False))
    )

    writer = DiagnosisWriter(live_client)
    report = {
        "pattern_signature": "integration_test:0:0:0",
        "reason": "Integration test — not a real diagnosis.",
        "confidence": 0.01,
    }

    assert writer.write_report(_INTEGRATION_TEST_URN, report) is True

    read_back = writer.read_diagnosis(_INTEGRATION_TEST_URN)
    assert read_back is not None
    assert read_back["pattern_signature"] == report["pattern_signature"]


def test_find_previous_diagnosis_locates_itself(live_client):
    """Validates the project's biggest known risk at runtime: does the search
    filter work (Plan A), or is the free-text fallback needed (Plan B)?"""
    writer = DiagnosisWriter(live_client)
    found = writer.find_previous_diagnosis(
        "integration_test:0:0:0", exclude_urn="urn:li:dataset:(urn:li:dataPlatform:hive,_nonexistent,PROD)"
    )
    assert found is not None, (
        "find_previous_diagnosis didn't find the entity "
        "test_write_then_read_diagnosis_round_trips already wrote. "
        "Check the search field name in _search_by_pattern_signature."
    )
    assert found["source_urn"] == _INTEGRATION_TEST_URN


def test_diagnose_seeded_graph_finds_root_cause_in_b(live_client):
    agent = MajesticAgent(live_client)
    report = agent.diagnose(_URN_C)

    if report["upstream_count"] == 0:
        pytest.skip("No lineage seeded — run `python3 scripts/seed_demo_data.py` first.")

    assert report["root_cause_urn"] == _URN_B
    assert report["causal_chain"][0]["evidence_type"] == "incident_tag"


def test_impact_seeded_graph_finds_dashboard(live_client):
    simulator = ImpactSimulator(live_client)
    impact = simulator.simulate(_URN_C)

    if impact["affected_datasets"] == 0:
        pytest.skip("No lineage seeded — run `python3 scripts/seed_demo_data.py` first.")

    assert impact["affected_dashboards"] >= 1
