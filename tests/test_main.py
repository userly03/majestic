from types import SimpleNamespace

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
