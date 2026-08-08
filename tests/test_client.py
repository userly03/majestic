from unittest.mock import patch

from config.settings import CONNECT_RETRY_ATTEMPTS
from src.graph.client import DataHubClient


def test_connects_successfully_on_first_try():
    with patch("src.graph.client.DataHubGraph") as MockGraph:
        MockGraph.return_value.test_connection.return_value = None

        client = DataHubClient(server_url="http://fake", token=None)

        assert client.is_connected is True
        assert MockGraph.return_value.test_connection.call_count == 1


def test_retries_on_transient_failure_then_succeeds():
    with patch("src.graph.client.DataHubGraph") as MockGraph, patch(
        "time.sleep", return_value=None
    ):
        MockGraph.return_value.test_connection.side_effect = [
            ConnectionError("boom"),
            ConnectionError("boom"),
            None,
        ]

        client = DataHubClient(server_url="http://fake", token=None)

        assert client.is_connected is True
        assert MockGraph.return_value.test_connection.call_count == 3


def test_gives_up_after_max_attempts_without_raising():
    with patch("src.graph.client.DataHubGraph") as MockGraph, patch(
        "time.sleep", return_value=None
    ):
        MockGraph.return_value.test_connection.side_effect = ConnectionError("boom")

        client = DataHubClient(server_url="http://fake", token=None)

        assert client.is_connected is False
        assert (
            MockGraph.return_value.test_connection.call_count == CONNECT_RETRY_ATTEMPTS
        )
