import time

from datahub.metadata.schema_classes import (
    AuditStampClass,
    DatasetPropertiesClass,
    GlobalTagsClass,
    OtherSchemaClass,
    OwnershipClass,
    SchemaMetadataClass,
    TagAssociationClass,
)

from src.core.diagnoser import RootCauseDiagnoser


def _millis_ago(hours: float) -> int:
    return int(time.time() * 1000 - hours * 3600 * 1000)


def _schema_changed(hours_ago: float) -> SchemaMetadataClass:
    return SchemaMetadataClass(
        schemaName="s",
        platform="urn:li:dataPlatform:hive",
        version=0,
        hash="",
        platformSchema=OtherSchemaClass(rawSchema=""),
        fields=[],
        lastModified=AuditStampClass(time=_millis_ago(hours_ago), actor="urn:li:corpuser:x"),
    )


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


# --- Mecanismo "lag-aware" (docs/LAG_AWARE_DIAGNOSIS.md) ---


def test_recency_decay_fresh_evidence_is_not_discounted():
    assert RootCauseDiagnoser._recency_decay(0.0) == 1.0


def test_recency_decay_old_evidence_is_discounted_but_never_zero():
    decay_at_one_halflife = RootCauseDiagnoser._recency_decay(48.0)  # default halflife
    assert decay_at_one_halflife == 0.5

    decay_very_old = RootCauseDiagnoser._recency_decay(48.0 * 20)
    assert 0.0 < decay_very_old < 0.001  # se acerca a 0, nunca llega


def test_recency_decay_without_timestamp_is_unaffected():
    # incident_tag / unowned no tienen age_hours disponible.
    assert RootCauseDiagnoser._recency_decay(None) == 1.0


def test_analyze_discounts_schema_change_older_than_recent_one(connected_client):
    def get_aspect(urn, aspect_type, version=0):
        if aspect_type is SchemaMetadataClass:
            if urn == "B":
                return _schema_changed(hours_ago=0.0)  # recién ocurrido, sin decaimiento
            if urn == "C":
                return _schema_changed(hours_ago=0.0)  # también recién ocurrido, mismo tipo
        return None

    connected_client.graph.get_aspect.side_effect = get_aspect

    diagnoser = RootCauseDiagnoser(connected_client)
    result = diagnoser.analyze(_upstream_nodes(("B", 1), ("C", 2)))

    b_entry = next(link for link in result["causal_chain"] if link["urn"] == "B")
    c_entry = next(link for link in result["causal_chain"] if link["urn"] == "C")

    # B (hop 1, más cerca del target) hereda el mismo evidence_type que C
    # (hop 2, más upstream) -> se descuenta.
    assert b_entry["adjusted_weight"] < b_entry["weight"]
    # C es el hop más lejano con ese tipo -> no se descuenta por herencia
    # (ambos son igual de recientes, así que el decaimiento es el mismo).
    assert c_entry["adjusted_weight"] == c_entry["weight"]
    # La causa raíz sigue siendo el hop más lejano evidenciado.
    assert result["root_cause_urn"] == "C"


def test_analyze_old_evidence_ranked_below_fresh_evidence_in_same_hop(connected_client):
    def get_aspect(urn, aspect_type, version=0):
        if urn == "B" and aspect_type is SchemaMetadataClass:
            return _schema_changed(hours_ago=0.5)  # fresco
        if urn == "C" and aspect_type is DatasetPropertiesClass:
            from datahub.metadata.schema_classes import TimeStampClass

            return DatasetPropertiesClass(
                name="c",
                lastModified=TimeStampClass(time=_millis_ago(23 * 24)),  # 23 días, muy viejo
            )
        return None

    connected_client.graph.get_aspect.side_effect = get_aspect

    diagnoser = RootCauseDiagnoser(connected_client)
    result = diagnoser.analyze(_upstream_nodes(("B", 1), ("C", 1)))

    assert len(result["causal_chain"]) == 2
    b_entry = next(link for link in result["causal_chain"] if link["urn"] == "B")
    c_entry = next(link for link in result["causal_chain"] if link["urn"] == "C")
    # C es stale_data (base 0.5) muy vieja -> decae mucho; B es schema_change
    # (base 0.7) recién ocurrido -> casi no decae. B debería rankear primero
    # pese a estar en el mismo hop.
    assert result["ranked_candidates"][0]["urn"] == "B"
    assert b_entry["adjusted_weight"] > c_entry["adjusted_weight"]


def test_ranked_candidates_capped_at_top_k(connected_client):
    from config.settings import RANKED_CANDIDATES_TOP_K

    def get_aspect(urn, aspect_type, version=0):
        if aspect_type is OwnershipClass:
            return OwnershipClass(owners=[])  # unowned en todos los hops
        return None

    connected_client.graph.get_aspect.side_effect = get_aspect

    diagnoser = RootCauseDiagnoser(connected_client)
    result = diagnoser.analyze(_upstream_nodes(("B", 1), ("C", 2), ("D", 3)))

    assert len(result["ranked_candidates"]) <= RANKED_CANDIDATES_TOP_K
    # Rankeado descendente por (hop, adjusted_weight): D (hop 3) primero.
    assert result["ranked_candidates"][0]["urn"] == "D"
