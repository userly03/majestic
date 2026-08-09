from unittest.mock import MagicMock

from datahub.metadata.schema_classes import CorpUserInfoClass, OwnerClass, OwnershipClass

from src.impact.simulator import ImpactSimulator


def _simulator_with_downstream(
    connected_client, downstream_nodes, owners_by_urn=None, display_names_by_urn=None
):
    simulator = ImpactSimulator(connected_client)
    simulator.traversal = MagicMock(get_downstream=MagicMock(return_value=downstream_nodes))

    owners_by_urn = owners_by_urn or {}
    display_names_by_urn = display_names_by_urn or {}

    def get_aspect(urn, aspect_type, version=0):
        if aspect_type is CorpUserInfoClass:
            name = display_names_by_urn.get(urn)
            return CorpUserInfoClass(active=True, displayName=name) if name else None
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


def test_simulate_single_downstream_node_uses_non_parallel_path(connected_client):
    # Un solo nodo downstream ejercita la rama sin ThreadPoolExecutor de
    # _collect_owners (len(urns) == 1).
    downstream = [{"urn": "d1", "entity_type": "dataset", "hop": 1}]
    owners_by_urn = {"d1": ["urn:li:corpuser:alice"]}
    simulator = _simulator_with_downstream(connected_client, downstream, owners_by_urn)

    result = simulator.simulate("A")

    assert result["affected_owners"] == ["urn:li:corpuser:alice"]
    # No CorpUserInfo available (display_names_by_urn wasn't passed), falls back to the URN.
    assert result["affected_owners_display"] == [
        {"urn": "urn:li:corpuser:alice", "name": "urn:li:corpuser:alice"}
    ]


def test_simulate_resolves_display_names_when_available(connected_client):
    downstream = [{"urn": "d1", "entity_type": "dataset", "hop": 1}]
    owners_by_urn = {"d1": ["urn:li:corpuser:alice"]}
    display_names_by_urn = {"urn:li:corpuser:alice": "Alice, equipo de Finanzas"}
    simulator = _simulator_with_downstream(
        connected_client, downstream, owners_by_urn, display_names_by_urn
    )

    result = simulator.simulate("A")

    assert result["affected_owners_display"] == [
        {"urn": "urn:li:corpuser:alice", "name": "Alice, equipo de Finanzas"}
    ]


def test_resolve_owner_names_falls_back_to_urn_on_error(connected_client):
    simulator = ImpactSimulator(connected_client)
    connected_client.graph.get_aspect.side_effect = Exception("boom")

    result = simulator._resolve_owner_names(["urn:li:corpuser:bob"])

    assert result == [{"urn": "urn:li:corpuser:bob", "name": "urn:li:corpuser:bob"}]


def test_resolve_owner_names_empty_list_returns_empty(connected_client):
    simulator = ImpactSimulator(connected_client)

    assert simulator._resolve_owner_names([]) == []


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
