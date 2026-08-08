from unittest.mock import MagicMock

from datahub.metadata.schema_classes import (
    StructuredPropertiesClass,
    StructuredPropertyValueAssignmentClass,
)

from src.memory.writer import DiagnosisWriter

_REPORT = {
    "pattern_signature": "stale_data:2:3:1",
    "reason": "algo se rompió",
    "confidence": 0.55,
}


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
    writer.write_report("urn:li:dataset:(x)", _REPORT, business_context="lección aprendida")

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
            _assignment("majestic.diagnosis", "algo se rompió"),
            _assignment("majestic.confidenceScore", 0.55),
        ]
    )

    writer = DiagnosisWriter(connected_client)
    result = writer.read_diagnosis("urn:li:dataset:(x)")

    assert result["pattern_signature"] == "stale_data:2:3:1"
    assert result["reason"] == "algo se rompió"
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
