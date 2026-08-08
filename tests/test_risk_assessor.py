from unittest.mock import MagicMock

from datahub.metadata.schema_classes import OwnerClass, OwnershipClass

from src.impact.risk_assessor import RiskAssessor


def _assessor_with_downstream(connected_client, downstream_nodes, owned_urns=None):
    assessor = RiskAssessor(connected_client)
    assessor.traversal = MagicMock(get_downstream=MagicMock(return_value=downstream_nodes))

    owned_urns = owned_urns or set()

    def get_aspect(urn, aspect_type, version=0):
        if urn in owned_urns:
            return OwnershipClass(owners=[OwnerClass(owner="urn:li:corpuser:alice", type="TECHNICAL_OWNER")])
        return OwnershipClass(owners=[])

    connected_client.graph.get_aspect.side_effect = get_aspect
    return assessor


def test_no_downstream_is_low_risk_and_not_blocked(connected_client):
    assessor = _assessor_with_downstream(connected_client, [])
    result = assessor.assess("A", {"risk_level": "none"})

    assert result["health_score"] == 1.0
    assert result["risk_label"] == "BAJO"
    assert result["should_block"] is False


def test_high_impact_with_fully_owned_downstream_is_less_risky_than_orphaned(connected_client):
    downstream = [
        {"urn": "d1", "entity_type": "dataset", "hop": 1},
        {"urn": "d2", "entity_type": "dataset", "hop": 1},
    ]

    owned_assessor = _assessor_with_downstream(connected_client, downstream, owned_urns={"d1", "d2"})
    owned_result = owned_assessor.assess("A", {"risk_level": "high"})

    orphaned_client = MagicMock()
    orphaned_client.is_connected = True
    orphaned_client.graph = MagicMock()
    orphaned_assessor = _assessor_with_downstream(orphaned_client, downstream, owned_urns=set())
    orphaned_result = orphaned_assessor.assess("A", {"risk_level": "high"})

    assert owned_result["health_score"] == 1.0
    assert orphaned_result["health_score"] == 0.0
    assert orphaned_result["risk_score"] > owned_result["risk_score"]


def test_high_risk_level_with_orphaned_downstream_blocks(connected_client):
    downstream = [{"urn": "d1", "entity_type": "dataset", "hop": 1}]
    assessor = _assessor_with_downstream(connected_client, downstream, owned_urns=set())

    result = assessor.assess("A", {"risk_level": "high"})

    assert result["risk_label"] == "ALTO"
    assert result["should_block"] is True


def test_partial_ownership_computes_intermediate_health_score(connected_client):
    downstream = [
        {"urn": "d1", "entity_type": "dataset", "hop": 1},
        {"urn": "d2", "entity_type": "dataset", "hop": 1},
    ]
    assessor = _assessor_with_downstream(connected_client, downstream, owned_urns={"d1"})

    result = assessor.assess("A", {"risk_level": "none"})

    assert result["health_score"] == 0.5


def test_unconnected_client_raises_at_construction():
    import pytest

    from src.graph.client import DataHubClient

    client = MagicMock(spec=DataHubClient)
    client.is_connected = False

    with pytest.raises(RuntimeError):
        RiskAssessor(client)
