import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

import main


def test_connection_error_maps_to_friendly_message():
    msg = main._human_error(requests.exceptions.ConnectionError("boom"))
    assert "No se pudo conectar" in msg


def test_timeout_maps_to_friendly_message():
    msg = main._human_error(requests.exceptions.Timeout("boom"))
    assert "No se pudo conectar" in msg


def test_http_404_maps_to_not_found_message():
    exc = requests.exceptions.HTTPError(response=SimpleNamespace(status_code=404))
    msg = main._human_error(exc)
    assert "no encontrado" in msg.lower()


def test_http_400_maps_to_invalid_urn_message():
    exc = requests.exceptions.HTTPError(response=SimpleNamespace(status_code=400))
    msg = main._human_error(exc)
    assert "formato inválido" in msg


def test_http_other_status_includes_status_code():
    exc = requests.exceptions.HTTPError(response=SimpleNamespace(status_code=500))
    msg = main._human_error(exc)
    assert "500" in msg


def test_runtime_error_passes_through_message():
    msg = main._human_error(RuntimeError("DataHubClient no está conectado."))
    assert msg == "DataHubClient no está conectado."


def test_generic_exception_falls_back_to_type_and_message():
    msg = main._human_error(ValueError("algo raro"))
    assert "ValueError" in msg
    assert "algo raro" in msg


def _run_main_with_args(argv):
    fake_client = SimpleNamespace(is_connected=False, graph=None)
    with patch.object(sys, "argv", ["main.py"] + argv), patch.object(
        main, "DataHubClient", return_value=fake_client
    ), patch("main.logging.basicConfig") as mock_basic_config, patch(
        "main.sys.exit"
    ):
        main.main()
    return mock_basic_config


def test_quiet_flag_sets_warning_level():
    mock_basic_config = _run_main_with_args(["--quiet", "doctor"])
    assert mock_basic_config.call_args.kwargs["level"] == logging.WARNING


def test_without_quiet_flag_sets_info_level():
    mock_basic_config = _run_main_with_args(["doctor"])
    assert mock_basic_config.call_args.kwargs["level"] == logging.INFO


def test_check_change_parses_required_urn_flag():
    # --urn es requerido: sin él, argparse debe fallar (SystemExit) antes
    # de siquiera intentar conectar a DataHub.
    import pytest

    with patch.object(sys, "argv", ["main.py", "check-change"]), pytest.raises(SystemExit):
        main.main()


def test_check_change_approves_low_risk_and_exits_zero(connected_client):
    with patch("main.ImpactSimulator") as MockSimulator, patch(
        "main.RiskAssessor"
    ) as MockAssessor, patch("main.sys.exit") as mock_exit:
        MockSimulator.return_value.simulate.return_value = {
            "source_urn": "A",
            "affected_datasets": 0,
            "affected_dashboards": 0,
            "affected_owners": [],
            "risk_level": "none",
        }
        MockAssessor.return_value.assess.return_value = {
            "urn": "A",
            "health_score": 1.0,
            "risk_score": 0.0,
            "risk_label": "BAJO",
            "should_block": False,
            "threshold": 0.5,
        }

        main.cmd_check_change(connected_client, "A")

        mock_exit.assert_called_once_with(0)


def test_check_change_blocks_high_risk_and_exits_one(connected_client):
    with patch("main.ImpactSimulator") as MockSimulator, patch(
        "main.RiskAssessor"
    ) as MockAssessor, patch("main.sys.exit") as mock_exit:
        MockSimulator.return_value.simulate.return_value = {
            "source_urn": "A",
            "affected_datasets": 5,
            "affected_dashboards": 2,
            "affected_owners": [],
            "risk_level": "high",
        }
        MockAssessor.return_value.assess.return_value = {
            "urn": "A",
            "health_score": 0.0,
            "risk_score": 0.84,
            "risk_label": "ALTO",
            "should_block": True,
            "threshold": 0.5,
        }

        main.cmd_check_change(connected_client, "A")

        mock_exit.assert_called_once_with(1)
