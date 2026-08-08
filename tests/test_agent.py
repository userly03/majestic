from unittest.mock import MagicMock

from src.core.agent import MajesticAgent


def _agent_with_mocks(connected_client, upstream, downstream, diagnosis):
    agent = MajesticAgent(connected_client)
    agent.traversal = MagicMock(get_upstream=MagicMock(return_value=upstream),
                                 get_downstream=MagicMock(return_value=downstream))
    agent.diagnoser = MagicMock(analyze=MagicMock(return_value=diagnosis))
    return agent


def test_diagnose_builds_pattern_signature_from_root_cause(connected_client):
    upstream = [{"urn": "B", "hop": 1}, {"urn": "C", "hop": 2}]
    downstream = [{"urn": "D", "hop": 1}]
    diagnosis = {
        "root_cause_urn": "C",
        "reason": "C (hop 2): stale",
        "causal_chain": [
            {"urn": "B", "hop": 1, "evidence_type": "unowned", "evidence": "x", "weight": 0.3},
            {"urn": "C", "hop": 2, "evidence_type": "stale_data", "evidence": "y", "weight": 0.5},
        ],
        "confidence": 0.4,
    }

    agent = _agent_with_mocks(connected_client, upstream, downstream, diagnosis)
    report = agent.diagnose("A")

    assert report["upstream_count"] == 2
    assert report["downstream_count"] == 1
    assert report["pattern_signature"] == "stale_data:2:2:1"


def test_diagnose_signature_when_no_root_cause(connected_client):
    diagnosis = {
        "root_cause_urn": None,
        "reason": "sin evidencia",
        "causal_chain": [],
        "confidence": 0.0,
    }

    agent = _agent_with_mocks(connected_client, [], [], diagnosis)
    report = agent.diagnose("A")

    assert report["pattern_signature"] == "unknown:0:0:0"
