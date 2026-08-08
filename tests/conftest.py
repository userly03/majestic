from unittest.mock import MagicMock

import pytest

from src.graph.client import DataHubClient


@pytest.fixture
def connected_client():
    """DataHubClient falso, ya 'conectado', con .graph mockeado."""
    client = MagicMock(spec=DataHubClient)
    client.is_connected = True
    client.graph = MagicMock()
    return client
