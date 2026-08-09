from unittest.mock import MagicMock, patch

from src.mcp_server import majestic_diagnose, majestic_impact


def test_majestic_diagnose_delegates_to_agent_and_returns_report(connected_client):
    report = {"root_cause_urn": "B", "pattern_signature": "stale_data:1:1:0"}
    with patch("src.mcp_server._get_client", return_value=connected_client), patch(
        "src.mcp_server.MajesticAgent"
    ) as agent_cls:
        agent_cls.return_value.diagnose.return_value = report

        result = majestic_diagnose("A")

        agent_cls.return_value.diagnose.assert_called_once_with("A")
        assert result == report


def test_majestic_diagnose_write_true_persists_report(connected_client):
    report = {"root_cause_urn": "B", "pattern_signature": "stale_data:1:1:0"}
    with patch("src.mcp_server._get_client", return_value=connected_client), patch(
        "src.mcp_server.MajesticAgent"
    ) as agent_cls, patch("src.mcp_server.DiagnosisWriter") as writer_cls:
        agent_cls.return_value.diagnose.return_value = report
        writer_cls.return_value.write_report.return_value = True

        result = majestic_diagnose("A", write=True)

        writer_cls.return_value.write_report.assert_called_once_with("A", report)
        assert result["written_to_datahub"] is True


def test_majestic_impact_delegates_to_simulator(connected_client):
    impact_report = {"risk_level": "high", "affected_datasets": 3}
    with patch("src.mcp_server._get_client", return_value=connected_client), patch(
        "src.mcp_server.ImpactSimulator"
    ) as simulator_cls:
        simulator_cls.return_value.simulate.return_value = impact_report

        result = majestic_impact("A")

        simulator_cls.return_value.simulate.assert_called_once_with("A")
        assert result == impact_report


def test_get_client_reuses_connected_client(connected_client):
    import src.mcp_server as mcp_server_module

    mcp_server_module._client = connected_client
    try:
        assert mcp_server_module._get_client() is connected_client
    finally:
        mcp_server_module._client = None


def test_get_client_reconnects_when_disconnected():
    import src.mcp_server as mcp_server_module

    stale_client = MagicMock(is_connected=False)
    fresh_client = MagicMock(is_connected=True)
    mcp_server_module._client = stale_client
    try:
        with patch("src.mcp_server.DataHubClient", return_value=fresh_client):
            assert mcp_server_module._get_client() is fresh_client
    finally:
        mcp_server_module._client = None
