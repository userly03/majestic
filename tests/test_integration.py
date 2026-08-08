"""
Tests de integración: corren contra una instancia real de DataHub, no
contra mocks. Cierran la brecha que dejan los tests unitarios (100% mocks)
entre "pasa en CI" y "funciona de verdad" — ver PROPOSAL.md, sección 2.

Se saltan automáticamente a menos que se opte explícitamente por
correrlos, para que un `pytest` local sin DataHub arriba siga siendo
instantáneo:

    MAJESTIC_RUN_INTEGRATION_TESTS=1 pytest -m integration

`test_diagnose_seeded_graph_finds_root_cause_in_b` y
`test_impact_seeded_graph_finds_dashboard` además requieren haber
corrido `python3 scripts/seed_demo_data.py` antes — si no, se saltan
con un mensaje explicando por qué (no fallan: la ausencia de datos
sembrados no es un bug del código).
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
            "Tests de integración desactivados por defecto. Correr con "
            "MAJESTIC_RUN_INTEGRATION_TESTS=1 pytest -m integration"
        )

    client = DataHubClient()
    if not client.is_connected:
        pytest.skip(
            "No hay una instancia real de DataHub disponible. "
            "Ejecuta: datahub docker quickstart"
        )
    return client


def test_write_then_read_diagnosis_round_trips(live_client):
    """Ciclo real de write-back: escribe structuredProperties y las lee de vuelta."""
    from datahub.emitter.mcp import MetadataChangeProposalWrapper
    from datahub.metadata.schema_classes import DatasetPropertiesClass, StatusClass

    live_client.graph.emit_mcp(
        MetadataChangeProposalWrapper(
            entityUrn=_INTEGRATION_TEST_URN,
            aspect=DatasetPropertiesClass(
                name="_majestic_integration_test",
                description="Entidad de test de integración. Seguro de ignorar/borrar.",
            ),
        )
    )
    live_client.graph.emit_mcp(
        MetadataChangeProposalWrapper(entityUrn=_INTEGRATION_TEST_URN, aspect=StatusClass(removed=False))
    )

    writer = DiagnosisWriter(live_client)
    report = {
        "pattern_signature": "integration_test:0:0:0",
        "reason": "Test de integración — no es un diagnóstico real.",
        "confidence": 0.01,
    }

    assert writer.write_report(_INTEGRATION_TEST_URN, report) is True

    read_back = writer.read_diagnosis(_INTEGRATION_TEST_URN)
    assert read_back is not None
    assert read_back["pattern_signature"] == report["pattern_signature"]


def test_find_previous_diagnosis_locates_itself(live_client):
    """Valida en runtime el riesgo #1 de PROPOSAL.md: ¿funciona el filtro
    de búsqueda (Plan A), o hace falta el fallback de texto libre (Plan B)?"""
    writer = DiagnosisWriter(live_client)
    found = writer.find_previous_diagnosis(
        "integration_test:0:0:0", exclude_urn="urn:li:dataset:(urn:li:dataPlatform:hive,_nonexistent,PROD)"
    )
    assert found is not None, (
        "find_previous_diagnosis no encontró la entidad que "
        "test_write_then_read_diagnosis_round_trips ya escribió. "
        "Revisar el nombre del campo de búsqueda en _search_by_pattern_signature."
    )
    assert found["source_urn"] == _INTEGRATION_TEST_URN


def test_diagnose_seeded_graph_finds_root_cause_in_b(live_client):
    agent = MajesticAgent(live_client)
    report = agent.diagnose(_URN_C)

    if report["upstream_count"] == 0:
        pytest.skip("No hay lineage sembrado — correr `python3 scripts/seed_demo_data.py` primero.")

    assert report["root_cause_urn"] == _URN_B
    assert report["causal_chain"][0]["evidence_type"] == "incident_tag"


def test_impact_seeded_graph_finds_dashboard(live_client):
    simulator = ImpactSimulator(live_client)
    impact = simulator.simulate(_URN_C)

    if impact["affected_datasets"] == 0:
        pytest.skip("No hay lineage sembrado — correr `python3 scripts/seed_demo_data.py` primero.")

    assert impact["affected_dashboards"] >= 1
