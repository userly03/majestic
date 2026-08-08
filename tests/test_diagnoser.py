from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlobalTagsClass,
    OwnershipClass,
    SchemaMetadataClass,
    TagAssociationClass,
)

from src.core.diagnoser import RootCauseDiagnoser


def _upstream_nodes(*hops):
    """hops: lista de (urn, hop)."""
    return [{"urn": urn, "hop": hop, "entity_type": "dataset"} for urn, hop in hops]


def test_analyze_finds_incident_tag_evidence(connected_client):
    def get_aspect(urn, aspect_type, version=0):
        if urn == "B" and aspect_type is GlobalTagsClass:
            return GlobalTagsClass(tags=[TagAssociationClass(tag="urn:li:tag:error_flagged")])
        return None

    connected_client.graph.get_aspect.side_effect = get_aspect

    diagnoser = RootCauseDiagnoser(connected_client)
    result = diagnoser.analyze(_upstream_nodes(("B", 1)))

    assert result["root_cause_urn"] == "B"
    assert result["causal_chain"][0]["evidence_type"] == "incident_tag"
    assert result["confidence"] > 0


def test_analyze_no_evidence_returns_empty_chain(connected_client):
    connected_client.graph.get_aspect.return_value = None

    diagnoser = RootCauseDiagnoser(connected_client)
    result = diagnoser.analyze(_upstream_nodes(("B", 1), ("C", 2)))

    assert result["root_cause_urn"] is None
    assert result["causal_chain"] == []
    assert result["confidence"] == 0.0


def test_analyze_stops_chain_at_first_unevidenced_hop(connected_client):
    # Hop 1 (B) no tiene evidencia; hop 2 (C) sí la tendría, pero no debe
    # llegar a evaluarse porque la cadena se corta en el primer salto sin evidencia.
    def get_aspect(urn, aspect_type, version=0):
        if urn == "C" and aspect_type is GlobalTagsClass:
            return GlobalTagsClass(tags=[TagAssociationClass(tag="urn:li:tag:error")])
        return None

    connected_client.graph.get_aspect.side_effect = get_aspect

    diagnoser = RootCauseDiagnoser(connected_client)
    result = diagnoser.analyze(_upstream_nodes(("B", 1), ("C", 2)))

    assert result["root_cause_urn"] is None
    assert result["causal_chain"] == []


def test_analyze_picks_farthest_evidenced_hop_as_root_cause(connected_client):
    def get_aspect(urn, aspect_type, version=0):
        if aspect_type is OwnershipClass:
            return OwnershipClass(owners=[])  # sin owner: evidencia en ambos
        return None

    connected_client.graph.get_aspect.side_effect = get_aspect

    diagnoser = RootCauseDiagnoser(connected_client)
    result = diagnoser.analyze(_upstream_nodes(("B", 1), ("C", 2)))

    assert result["root_cause_urn"] == "C"
    assert len(result["causal_chain"]) == 2


def test_analyze_evaluates_multiple_nodes_in_same_hop_in_parallel(connected_client):
    # B y C están en el MISMO hop -> ejercita la rama con ThreadPoolExecutor
    # de _collect_evidence_parallel (no la secuencial de un solo nodo).
    def get_aspect(urn, aspect_type, version=0):
        if urn == "B" and aspect_type is GlobalTagsClass:
            return GlobalTagsClass(tags=[TagAssociationClass(tag="urn:li:tag:incident")])
        return None

    connected_client.graph.get_aspect.side_effect = get_aspect

    diagnoser = RootCauseDiagnoser(connected_client)
    result = diagnoser.analyze(_upstream_nodes(("B", 1), ("C", 1)))

    assert result["root_cause_urn"] == "B"
    assert len(result["causal_chain"]) == 1


def test_get_aspect_cached_avoids_duplicate_calls(connected_client):
    connected_client.graph.get_aspect.return_value = None

    diagnoser = RootCauseDiagnoser(connected_client)
    diagnoser._get_aspect_cached("B", GlobalTagsClass)
    diagnoser._get_aspect_cached("B", GlobalTagsClass)

    assert connected_client.graph.get_aspect.call_count == 1


def test_get_aspect_cached_distinguishes_by_aspect_type(connected_client):
    connected_client.graph.get_aspect.return_value = None

    diagnoser = RootCauseDiagnoser(connected_client)
    diagnoser._get_aspect_cached("B", GlobalTagsClass)
    diagnoser._get_aspect_cached("B", OwnershipClass)

    assert connected_client.graph.get_aspect.call_count == 2
