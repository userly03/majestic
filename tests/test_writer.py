from unittest.mock import MagicMock

from datahub.metadata.schema_classes import (
    StructuredPropertiesClass,
    StructuredPropertyValueAssignmentClass,
)

from src.memory.writer import DiagnosisWriter, _sanitize_urn_lookalikes

_REPORT = {
    "pattern_signature": "stale_data:2:3:1",
    "reason": "something broke",
    "confidence": 0.55,
}


def test_sanitize_urn_lookalikes_breaks_urn_prefix():
    text = "urn:li:dataset:(urn:li:dataPlatform:hive,x.y,PROD) (hop 1): no owner"

    sanitized = _sanitize_urn_lookalikes(text)

    assert "urn:li:" not in sanitized
    assert "urn:​li:" in sanitized
    # Visually identical (the zero-width space isn't visible when printed).
    assert sanitized.replace("​", "") == text


def test_sanitize_urn_lookalikes_leaves_text_without_urns_untouched():
    text = "dataset has no assigned owner, no relation to any URN"

    assert _sanitize_urn_lookalikes(text) == text


def test_sanitize_urn_lookalikes_handles_multiple_occurrences():
    text = "urn:li:dataset:(a) inherited from urn:li:dataset:(b)"

    sanitized = _sanitize_urn_lookalikes(text)

    assert sanitized.count("urn:​li:") == 2


def test_write_report_success(connected_client):
    writer = DiagnosisWriter(connected_client)
    ok = writer.write_report("urn:li:dataset:(x)", _REPORT)

    assert ok is True
    connected_client.graph.emit_mcps.assert_called_once()


def test_write_report_failure_returns_false(connected_client):
    connected_client.graph.emit_mcps.side_effect = Exception("boom")
    writer = DiagnosisWriter(connected_client)

    ok = writer.write_report("urn:li:dataset:(x)", _REPORT)

    assert ok is False


def test_write_report_skips_business_context_when_not_given(connected_client):
    writer = DiagnosisWriter(connected_client)
    writer.write_report("urn:li:dataset:(x)", _REPORT)

    mcps = connected_client.graph.emit_mcps.call_args[0][0]
    patch_bytes = b"".join(mcp.aspect.value for mcp in mcps if mcp.aspect is not None)
    assert b"majestic.businessContext" not in patch_bytes
    assert b"majestic.patternSignature" in patch_bytes


def test_write_report_includes_business_context_when_given(connected_client):
    writer = DiagnosisWriter(connected_client)
    writer.write_report("urn:li:dataset:(x)", _REPORT, business_context="lesson learned")

    mcps = connected_client.graph.emit_mcps.call_args[0][0]
    patch_bytes = b"".join(mcp.aspect.value for mcp in mcps if mcp.aspect is not None)
    assert b"majestic.businessContext" in patch_bytes


def _assignment(prop_id, value):
    return StructuredPropertyValueAssignmentClass(
        propertyUrn=f"urn:li:structuredProperty:{prop_id}", values=[value]
    )


def test_read_diagnosis_parses_structured_properties(connected_client):
    connected_client.graph.get_aspect.return_value = StructuredPropertiesClass(
        properties=[
            _assignment("majestic.patternSignature", "stale_data:2:3:1"),
            _assignment("majestic.diagnosis", "something broke"),
            _assignment("majestic.confidenceScore", 0.55),
        ]
    )

    writer = DiagnosisWriter(connected_client)
    result = writer.read_diagnosis("urn:li:dataset:(x)")

    assert result["pattern_signature"] == "stale_data:2:3:1"
    assert result["reason"] == "something broke"
    assert result["confidence"] == 0.55


def test_read_diagnosis_returns_none_when_no_properties(connected_client):
    connected_client.graph.get_aspect.return_value = None

    writer = DiagnosisWriter(connected_client)
    result = writer.read_diagnosis("urn:li:dataset:(x)")

    assert result is None


def test_find_previous_diagnosis_skips_excluded_urn(connected_client):
    connected_client.graph.get_urns_by_filter.return_value = iter(["A", "B"])
    writer = DiagnosisWriter(connected_client)
    writer.read_diagnosis = MagicMock(
        side_effect=lambda urn: {"pattern_signature": "sig"} if urn == "B" else None
    )

    result = writer.find_previous_diagnosis("sig", exclude_urn="A")

    assert result["source_urn"] == "B"


def test_find_previous_diagnosis_rejects_plan_b_false_positive(connected_client):
    # Plan B is free text: it can bring a candidate whose real signature
    # doesn't exactly match. That partial match must not be accepted.
    connected_client.graph.get_urns_by_filter.return_value = iter(["A"])
    writer = DiagnosisWriter(connected_client)
    writer.read_diagnosis = MagicMock(return_value={"pattern_signature": "other_signature:9:9:9"})

    result = writer.find_previous_diagnosis("sig:1:2:3")

    assert result is None


def test_find_previous_diagnosis_skips_candidate_that_fails_to_read(connected_client):
    connected_client.graph.get_urns_by_filter.return_value = iter(["A", "B"])
    writer = DiagnosisWriter(connected_client)

    def flaky_read(urn):
        if urn == "A":
            raise Exception("boom")
        return {"pattern_signature": "sig"}

    writer.read_diagnosis = MagicMock(side_effect=flaky_read)

    result = writer.find_previous_diagnosis("sig")

    assert result["source_urn"] == "B"


def test_search_falls_back_to_plan_b_when_plan_a_raises(connected_client):
    connected_client.graph.get_urns_by_filter.side_effect = [
        Exception("invalid search field"),
        iter(["B"]),
    ]
    writer = DiagnosisWriter(connected_client)

    result = writer._search_by_pattern_signature("sig")

    assert result == ["B"]
    assert connected_client.graph.get_urns_by_filter.call_count == 2
    # Plan B must be a free-text search (query=), not extraFilters.
    _, plan_b_kwargs = connected_client.graph.get_urns_by_filter.call_args_list[1]
    assert plan_b_kwargs.get("query") == "sig"


def test_search_falls_back_to_plan_b_when_plan_a_returns_nothing(connected_client):
    connected_client.graph.get_urns_by_filter.side_effect = [iter([]), iter(["C"])]
    writer = DiagnosisWriter(connected_client)

    result = writer._search_by_pattern_signature("sig")

    assert result == ["C"]
    assert connected_client.graph.get_urns_by_filter.call_count == 2


def test_search_returns_empty_when_both_plans_fail(connected_client):
    connected_client.graph.get_urns_by_filter.side_effect = Exception("boom")
    writer = DiagnosisWriter(connected_client)

    result = writer._search_by_pattern_signature("sig")

    assert result == []
