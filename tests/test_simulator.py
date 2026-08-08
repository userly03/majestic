from unittest.mock import MagicMock

from datahub.metadata.schema_classes import OwnerClass, OwnershipClass

from src.impact.simulator import ImpactSimulator


def _simulator_with_downstream(connected_client, downstream_nodes, owners_by_urn=None):
    simulator = ImpactSimulator(connected_client)
    simulator.traversal = MagicMock(get_downstream=MagicMock(return_value=downstream_nodes))

    owners_by_urn = owners_by_urn or {}

    def get_aspect(urn, aspect_type, version=0):
        owner_urns = owners_by_urn.get(urn, [])
        return OwnershipClass(owners=[OwnerClass(owner=o, type="TECHNICAL_OWNER") for o in owner_urns])

    connected_client.graph.get_aspect.side_effect = get_aspect
    return simulator


def test_simulate_counts_dashboards_and_risk_high(connected_client):
    downstream = [
        {"urn": "d1", "entity_type": "dataset", "hop": 1},
        {"urn": "dash1", "entity_type": "dashboard", "hop": 1},
    ]
    simulator = _simulator_with_downstream(connected_client, downstream)

    result = simulator.simulate("A")

    assert result["affected_datasets"] == 2
    assert result["affected_dashboards"] == 1
    assert result["risk_level"] == "high"


def test_simulate_no_downstream_is_no_risk(connected_client):
    simulator = _simulator_with_downstream(connected_client, [])
    result = simulator.simulate("A")

    assert result["risk_level"] == "none"
    assert result["affected_owners"] == []


def test_simulate_collects_deduped_sorted_owners(connected_client):
    downstream = [
        {"urn": "d1", "entity_type": "dataset", "hop": 1},
        {"urn": "d2", "entity_type": "dataset", "hop": 1},
    ]
    owners_by_urn = {
        "d1": ["urn:li:corpuser:bob", "urn:li:corpuser:alice"],
        "d2": ["urn:li:corpuser:alice"],
    }
    simulator = _simulator_with_downstream(connected_client, downstream, owners_by_urn)

    result = simulator.simulate("A")

    assert result["affected_owners"] == ["urn:li:corpuser:alice", "urn:li:corpuser:bob"]
    assert result["risk_level"] == "medium"
