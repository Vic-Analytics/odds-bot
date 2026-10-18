"""Tests for the retry helper. No real network is used."""

import pytest
import requests

import http_utils


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


@pytest.fixture
def network(monkeypatch):
    """Replace requests.request with a script of results, and record the waits."""
    state = {"calls": 0, "waits": [], "script": []}

    def fake_request(method, url, **kwargs):
        item = state["script"][state["calls"]]
        state["calls"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(http_utils.requests, "request", fake_request)
    monkeypatch.setattr(http_utils.time, "sleep", lambda seconds: state["waits"].append(seconds))
    return state


URL = "https://api.example.com/v4/x?apiKey=SECRET123"


def test_success_on_first_try_makes_one_call(network):
    network["script"] = [FakeResponse(200)]
    assert http_utils.request_with_retries("GET", URL).status_code == 200
    assert network["calls"] == 1 and network["waits"] == []


def test_network_errors_are_retried_then_succeed(network):
    network["script"] = [requests.ConnectionError("x"), requests.Timeout("y"), FakeResponse(200)]
    assert http_utils.request_with_retries("GET", URL).status_code == 200
    assert network["calls"] == 3
    assert network["waits"] == [2, 6]


def test_server_error_is_retried(network):
    network["script"] = [FakeResponse(503), FakeResponse(200)]
    assert http_utils.request_with_retries("GET", URL).status_code == 200
    assert network["calls"] == 2


def test_client_errors_are_not_retried(network):
    network["script"] = [FakeResponse(401)]
    assert http_utils.request_with_retries("GET", URL).status_code == 401
    assert network["calls"] == 1


def test_429_is_not_retried_by_default(network):
    # For the Odds API a 429 usually means the monthly credits are gone.
    network["script"] = [FakeResponse(429)]
    assert http_utils.request_with_retries("GET", URL).status_code == 429
    assert network["calls"] == 1


def test_persistent_server_error_returns_the_last_response(network):
    network["script"] = [FakeResponse(503)] * 3
    assert http_utils.request_with_retries("GET", URL).status_code == 503
    assert network["calls"] == 3


def test_persistent_network_error_raises_without_leaking_the_url(network):
    network["script"] = [requests.Timeout("failed for ...?apiKey=SECRET123")] * 3
    with pytest.raises(RuntimeError) as error:
        http_utils.request_with_retries("GET", URL)
    message = str(error.value)
    assert "SECRET123" not in message
    assert "api.example.com" in message and "Timeout" in message and "3 times" in message


def test_telegram_429_waits_as_long_as_asked(network):
    network["script"] = [FakeResponse(429, {"parameters": {"retry_after": 3}}), FakeResponse(200)]
    assert http_utils.request_with_retries("POST", URL, retry_429=True).status_code == 200
    assert network["waits"] == [3]


def test_telegram_429_wait_is_capped_at_30_seconds(network):
    network["script"] = [FakeResponse(429, {"parameters": {"retry_after": 999}}), FakeResponse(200)]
    http_utils.request_with_retries("POST", URL, retry_429=True)
    assert network["waits"] == [30]
