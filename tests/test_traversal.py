from types import SimpleNamespace

from src.graph.traversal import LineageTraversal


def _rel(source_urn, dest_urn, source_type="dataset", dest_type="dataset", rel="DownstreamOf"):
    return SimpleNamespace(
        source_urn=source_urn,
        destination_urn=dest_urn,
        source_entity_type=source_type,
        destination_entity_type=dest_type,
        relationship_type=rel,
    )


def _scroll_result(relationships, scroll_id=None):
    return SimpleNamespace(relationships=relationships, scroll_id=scroll_id)


def test_get_upstream_bfs_multi_hop(connected_client):
    # A <- B <- C  (B es upstream de A, C es upstream de B)
    def side_effect(*, urns, direction, count, scroll_id):
        anchor = urns[0]
        if anchor == "A":
            return _scroll_result([_rel(source_urn="B", dest_urn="A")])
        if anchor == "B":
            return _scroll_result([_rel(source_urn="C", dest_urn="B")])
        return _scroll_result([])

    connected_client.graph.scroll_lineage.side_effect = side_effect

    traversal = LineageTraversal(connected_client)
    nodes = traversal.get_upstream("A", max_hops=3)

    urns = {n["urn"]: n["hop"] for n in nodes}
    assert urns == {"B": 1, "C": 2}


def test_get_upstream_respects_max_hops(connected_client):
    def side_effect(*, urns, direction, count, scroll_id):
        anchor = urns[0]
        if anchor == "A":
            return _scroll_result([_rel(source_urn="B", dest_urn="A")])
        if anchor == "B":
            return _scroll_result([_rel(source_urn="C", dest_urn="B")])
        return _scroll_result([])

    connected_client.graph.scroll_lineage.side_effect = side_effect

    traversal = LineageTraversal(connected_client)
    nodes = traversal.get_upstream("A", max_hops=1)

    assert [n["urn"] for n in nodes] == ["B"]


def test_get_upstream_dedupes_diamond(connected_client):
    # A <- B, A <- C, B <- D, C <- D  (D no debe repetirse)
    def side_effect(*, urns, direction, count, scroll_id):
        anchor = urns[0]
        if anchor == "A":
            return _scroll_result(
                [_rel(source_urn="B", dest_urn="A"), _rel(source_urn="C", dest_urn="A")]
            )
        if anchor in ("B", "C"):
            return _scroll_result([_rel(source_urn="D", dest_urn=anchor)])
        return _scroll_result([])

    connected_client.graph.scroll_lineage.side_effect = side_effect

    traversal = LineageTraversal(connected_client)
    nodes = traversal.get_upstream("A", max_hops=3)

    d_nodes = [n for n in nodes if n["urn"] == "D"]
    assert len(d_nodes) == 1


def test_get_downstream_captures_entity_type(connected_client):
    connected_client.graph.scroll_lineage.side_effect = [
        _scroll_result([_rel(source_urn="A", dest_urn="dash1", dest_type="dashboard")]),
        _scroll_result([]),
    ]

    traversal = LineageTraversal(connected_client)
    nodes = traversal.get_downstream("A", max_hops=1)

    assert nodes[0]["entity_type"] == "dashboard"


def test_get_upstream_paginates_multi_page_response(connected_client):
    # scroll_lineage can return the relationship across several pages for
    # the same anchor; _one_hop must follow scroll_id until it's None and
    # merge results from every page, not just the first.
    call_scroll_ids = []

    def side_effect(*, urns, direction, count, scroll_id):
        call_scroll_ids.append(scroll_id)
        if scroll_id is None:
            # First page: brings a scroll_id to request the second one.
            return _scroll_result([_rel(source_urn="B1", dest_urn="A")], scroll_id="page-2")
        if scroll_id == "page-2":
            # Second page: no more scroll_id, pagination ends here.
            return _scroll_result([_rel(source_urn="B2", dest_urn="A")], scroll_id=None)
        raise AssertionError(f"unexpected scroll_id: {scroll_id!r}")

    connected_client.graph.scroll_lineage.side_effect = side_effect

    traversal = LineageTraversal(connected_client)
    nodes = traversal.get_upstream("A", max_hops=1)

    assert {n["urn"] for n in nodes} == {"B1", "B2"}
    assert call_scroll_ids == [None, "page-2"]
    assert connected_client.graph.scroll_lineage.call_count == 2


def test_traversal_raises_if_client_not_connected(connected_client):
    connected_client.is_connected = False
    try:
        LineageTraversal(connected_client)
        assert False, "should have raised RuntimeError"
    except RuntimeError:
        pass
