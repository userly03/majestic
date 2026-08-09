from src.core.narrator import explain


def test_explain_no_evidence_reports_no_root_cause():
    report = {
        "target_urn": "C",
        "root_cause_urn": None,
        "causal_chain": [],
        "confidence": 0.0,
    }

    text = explain(report)

    assert "No concrete evidence" in text
    assert "C" in text


def test_explain_describes_each_link_in_the_chain():
    report = {
        "target_urn": "C",
        "root_cause_urn": "B",
        "causal_chain": [
            {
                "urn": "B",
                "hop": 1,
                "evidence_type": "incident_tag",
                "evidence": "tag 'urn:li:tag:incident' matches incident keyword 'incident'",
                "weight": 0.9,
            }
        ],
        "confidence": 0.9,
    }

    text = explain(report)

    assert "C" in text
    assert "B" in text
    assert "Hop 1" in text
    assert "90%" in text


def test_explain_never_raises_on_missing_optional_fields():
    # minimal report, no 'target_urn' — shouldn't blow up.
    text = explain({"causal_chain": [], "confidence": 0.0})
    assert isinstance(text, str)
    assert len(text) > 0
