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
    # Hop 1 (B) has no evidence; hop 2 (C) would have some, but it must
    # never be evaluated because the chain stops at the first hop with no evidence.
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
            return OwnershipClass(owners=[])  # no owner: evidence on both
        return None

    connected_client.graph.get_aspect.side_effect = get_aspect

    diagnoser = RootCauseDiagnoser(connected_client)
    result = diagnoser.analyze(_upstream_nodes(("B", 1), ("C", 2)))

    assert result["root_cause_urn"] == "C"
    assert len(result["causal_chain"]) == 2


def test_analyze_evaluates_multiple_nodes_in_same_hop_in_parallel(connected_client):
    # B and C are at the SAME hop -> exercises _collect_evidence_parallel's
    # ThreadPoolExecutor branch (not the single-node sequential path).
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


# --- "lag-aware" mechanism (docs/LAG_AWARE_DIAGNOSIS.md) ---


def test_recency_decay_fresh_evidence_is_not_discounted():
    assert RootCauseDiagnoser._recency_decay(0.0) == 1.0


def test_recency_decay_old_evidence_is_discounted_but_never_zero():
    decay_at_one_halflife = RootCauseDiagnoser._recency_decay(48.0)  # default halflife
    assert decay_at_one_halflife == 0.5

    decay_very_old = RootCauseDiagnoser._recency_decay(48.0 * 20)
    assert 0.0 < decay_very_old < 0.001  # approaches 0, never reaches it


def test_recency_decay_without_timestamp_is_unaffected():
    # incident_tag / unowned have no age_hours available.
    assert RootCauseDiagnoser._recency_decay(None) == 1.0


def test_analyze_discounts_schema_change_older_than_recent_one(connected_client):
    def get_aspect(urn, aspect_type, version=0):
        if aspect_type is SchemaMetadataClass:
            if urn == "B":
                return _schema_changed(hours_ago=0.0)  # just happened, no decay
            if urn == "C":
                return _schema_changed(hours_ago=0.0)  # also just happened, same type
        return None

    connected_client.graph.get_aspect.side_effect = get_aspect

    diagnoser = RootCauseDiagnoser(connected_client)
    result = diagnoser.analyze(_upstream_nodes(("B", 1), ("C", 2)))

    b_entry = next(link for link in result["causal_chain"] if link["urn"] == "B")
    c_entry = next(link for link in result["causal_chain"] if link["urn"] == "C")

    # B (hop 1, closer to the target) inherits the same evidence_type as C
    # (hop 2, farther upstream) -> gets discounted.
    assert b_entry["adjusted_weight"] < b_entry["weight"]
    # C is the farthest hop with that type -> not discounted for inheritance
    # (both are equally recent, so the decay is the same).
    assert c_entry["adjusted_weight"] == c_entry["weight"]
    # The root cause is still the farthest evidenced hop.
    assert result["root_cause_urn"] == "C"


def test_analyze_old_evidence_ranked_below_fresh_evidence_in_same_hop(connected_client):
    def get_aspect(urn, aspect_type, version=0):
        if urn == "B" and aspect_type is SchemaMetadataClass:
            return _schema_changed(hours_ago=0.5)  # fresh
        if urn == "C" and aspect_type is DatasetPropertiesClass:
            from datahub.metadata.schema_classes import TimeStampClass

            return DatasetPropertiesClass(
                name="c",
                lastModified=TimeStampClass(time=_millis_ago(23 * 24)),  # 23 days, very old
            )
        return None

    connected_client.graph.get_aspect.side_effect = get_aspect

    diagnoser = RootCauseDiagnoser(connected_client)
    result = diagnoser.analyze(_upstream_nodes(("B", 1), ("C", 1)))

    assert len(result["causal_chain"]) == 2
    b_entry = next(link for link in result["causal_chain"] if link["urn"] == "B")
    c_entry = next(link for link in result["causal_chain"] if link["urn"] == "C")
    # C is stale_data (base 0.5) very old -> decays a lot; B is schema_change
    # (base 0.7) just happened -> barely decays. B should rank first
    # despite being at the same hop.
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
