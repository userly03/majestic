from unittest.mock import MagicMock

import pytest

from src.events.listener import IncidentListener
from src.graph.client import DataHubClient


def _listener_with_mocks(connected_client, urls_by_keyword=None):
    listener = IncidentListener(connected_client)
    listener._diagnoser = MagicMock()
    listener._agent = MagicMock()

    urls_by_keyword = urls_by_keyword or {}

    def get_urns_by_filter(entity_types=None, query=None, **kwargs):
        return urls_by_keyword.get(query, [])

    connected_client.graph.get_urns_by_filter.side_effect = get_urns_by_filter
    return listener


def test_unconnected_client_raises_at_construction():
    client = MagicMock(spec=DataHubClient)
    client.is_connected = False

    with pytest.raises(RuntimeError):
        IncidentListener(client)


def test_poll_once_diagnoses_new_urn_with_real_incident_tag(connected_client):
    listener = _listener_with_mocks(connected_client, urls_by_keyword={"incident": ["urn:A"]})
    listener._diagnoser._check_incident_tags.return_value = {
        "evidence_type": "incident_tag",
        "evidence": "tag 'urn:li:tag:incident' coincide con palabra clave de incidente 'incident'",
        "weight": 0.9,
    }
    listener._agent.diagnose.return_value = {
        "root_cause_urn": "urn:B",
        "reason": "urn:B (hop 1): tag de incidente",
        "confidence": 0.9,
    }

    processed = listener.poll_once()

    assert processed == 1
    listener._agent.diagnose.assert_called_once_with("urn:A")
    assert "urn:A" in listener._seen_urns


def test_poll_once_skips_urn_already_seen(connected_client):
    listener = _listener_with_mocks(connected_client, urls_by_keyword={"incident": ["urn:A"]})
    listener._seen_urns.add("urn:A")

    processed = listener.poll_once()

    assert processed == 0
    listener._agent.diagnose.assert_not_called()


def test_poll_once_discards_free_text_false_positive(connected_client):
    """La búsqueda de texto libre encuentra 'urn:A' (coincidió con la
    palabra en una descripción), pero el chequeo real de tags dice que no
    tiene un tag de incidente de verdad — no debe diagnosticarse."""
    listener = _listener_with_mocks(connected_client, urls_by_keyword={"incident": ["urn:A"]})
    listener._diagnoser._check_incident_tags.return_value = None

    processed = listener.poll_once()

    assert processed == 0
    listener._agent.diagnose.assert_not_called()
    # Igual se marca como visto, para no re-evaluarlo en cada ciclo.
    assert "urn:A" in listener._seen_urns


def test_poll_once_dedupes_candidates_found_by_multiple_keywords(connected_client):
    listener = _listener_with_mocks(
        connected_client,
        urls_by_keyword={"incident": ["urn:A"], "broken": ["urn:A"], "error": [], "deprecated": [], "anomaly": []},
    )
    listener._diagnoser._check_incident_tags.return_value = {
        "evidence_type": "incident_tag",
        "evidence": "tag coincide",
        "weight": 0.9,
    }
    listener._agent.diagnose.return_value = {"root_cause_urn": None, "reason": "x", "confidence": 0.0}

    processed = listener.poll_once()

    assert processed == 1
    listener._agent.diagnose.assert_called_once_with("urn:A")


def test_run_once_calls_poll_once_exactly_once_without_sleeping(connected_client, monkeypatch):
    listener = _listener_with_mocks(connected_client)
    listener.poll_once = MagicMock(return_value=0)

    sleep_calls = []
    monkeypatch.setattr("src.events.listener.time.sleep", lambda s: sleep_calls.append(s))

    listener.run(once=True)

    listener.poll_once.assert_called_once()
    assert sleep_calls == []


def test_poll_once_survives_search_failure_for_one_keyword(connected_client):
    listener = IncidentListener(connected_client)
    listener._diagnoser = MagicMock()
    listener._agent = MagicMock()

    def get_urns_by_filter(entity_types=None, query=None, **kwargs):
        if query == "incident":
            raise RuntimeError("GMS caído")
        return []

    connected_client.graph.get_urns_by_filter.side_effect = get_urns_by_filter

    processed = listener.poll_once()

    assert processed == 0
    listener._agent.diagnose.assert_not_called()
