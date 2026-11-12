"""Tests for the missed-message alarm pings (digest and recap). Fake network only: nothing is ever contacted."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import requests

import http_utils

SCRIPT = Path(__file__).parent.parent / "scripts" / "ping_healthcheck.py"
spec = importlib.util.spec_from_file_location("ping_healthcheck", SCRIPT)
ping_healthcheck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ping_healthcheck)

URL = "https://hc-ping.com/11111111-2222-3333-4444-SECRETSECRET"


class FakeResponse:
    def __init__(self, status):
        self.status_code = status
        self.ok = status < 400


@pytest.fixture
def network(monkeypatch):
    """Replace the web with a script of answers; records every request."""
    calls = []
    answers = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        answer = answers.pop(0) if answers else FakeResponse(200)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(http_utils.requests, "request", fake_request)
    monkeypatch.setattr(http_utils.time, "sleep", lambda s: None)
    monkeypatch.delenv("HEALTHCHECK_PING_URL", raising=False)
    return type("Network", (), {"calls": calls, "answers": answers})


def never_leaks_the_url(capsys):
    out = capsys.readouterr()
    assert "SECRETSECRET" not in out.out + out.err


def test_a_successful_ping(network, capsys):
    assert ping_healthcheck.ping(URL) is True
    assert [(method, url) for method, url, _ in network.calls] == [("GET", URL)]
    assert network.calls[0][2]["timeout"] == 10            # never waits longer than 10 seconds per try
    never_leaks_the_url(capsys)


def test_no_secret_means_no_ping_and_no_network_call(network, capsys):
    assert ping_healthcheck.ping() is False
    assert network.calls == []
    assert "not set" in capsys.readouterr().err


def test_the_url_is_read_from_the_environment_and_whitespace_is_ignored(network, monkeypatch):
    monkeypatch.setenv("HEALTHCHECK_PING_URL", f"  {URL}\n")
    assert ping_healthcheck.ping() is True
    assert network.calls[0][1] == URL


def test_a_plain_http_url_is_refused(network, capsys):
    assert ping_healthcheck.ping("http://hc-ping.com/abc") is False
    assert network.calls == []
    assert "https" in capsys.readouterr().err


def test_a_server_error_is_retried_then_reported_without_raising(network, capsys):
    network.answers[:] = [FakeResponse(500), FakeResponse(503), FakeResponse(502)]
    assert ping_healthcheck.ping(URL) is False
    assert len(network.calls) == 3                          # three tries, then it gives up
    assert "HTTP 502" in capsys.readouterr().err


def test_a_server_error_that_clears_up_counts_as_a_success(network):
    network.answers[:] = [FakeResponse(503), FakeResponse(200)]
    assert ping_healthcheck.ping(URL) is True
    assert len(network.calls) == 2


def test_a_wrong_url_is_not_retried(network, capsys):
    network.answers[:] = [FakeResponse(404)]
    assert ping_healthcheck.ping(URL) is False
    assert len(network.calls) == 1
    assert "check the URL" in capsys.readouterr().err
    never_leaks_the_url(capsys)


def test_a_network_error_never_raises_and_never_prints_the_url(network, capsys):
    network.answers[:] = [requests.ConnectionError(f"Max retries exceeded with url: {URL}")] * 3
    assert ping_healthcheck.ping(URL) is False
    out = capsys.readouterr()
    assert "SECRETSECRET" not in out.out + out.err
    assert "RuntimeError" in out.err or "ConnectionError" in out.err


def test_even_an_unexpected_error_is_swallowed(network, capsys):
    network.answers[:] = [ValueError(f"bad url {URL}")]
    assert ping_healthcheck.ping(URL) is False
    never_leaks_the_url(capsys)


@pytest.mark.parametrize("answers", [[FakeResponse(200)], [FakeResponse(500)] * 3, [requests.Timeout("slow")] * 3, [KeyError("x")]])
def test_main_always_exits_zero(network, monkeypatch, answers):
    monkeypatch.setenv("HEALTHCHECK_PING_URL", URL)
    network.answers[:] = answers
    assert ping_healthcheck.main([]) == 0


def test_running_the_script_without_a_secret_exits_zero(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=tmp_path,
                            env={"PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    assert result.returncode == 0
    assert "not set" in result.stderr


# ---------- the second check: the results recap has its own secret ----------

RECAP_URL = "https://hc-ping.com/99999999-8888-7777-6666-SECRETSECRET"


def test_the_recap_check_uses_its_own_secret_and_never_the_digests(network, monkeypatch):
    monkeypatch.setenv("HEALTHCHECK_PING_URL", URL)
    monkeypatch.setenv("HEALTHCHECK_RECAP_PING_URL", RECAP_URL)
    assert ping_healthcheck.main(["--url-env", "HEALTHCHECK_RECAP_PING_URL"]) == 0
    assert [url for _, url, _ in network.calls] == [RECAP_URL]


def test_the_digest_check_still_uses_the_digest_secret_by_default(network, monkeypatch):
    monkeypatch.setenv("HEALTHCHECK_PING_URL", URL)
    monkeypatch.setenv("HEALTHCHECK_RECAP_PING_URL", RECAP_URL)
    assert ping_healthcheck.main([]) == 0
    assert [url for _, url, _ in network.calls] == [URL]


def test_the_recap_check_does_nothing_without_its_own_secret_even_if_the_digest_secret_is_set(network, monkeypatch, capsys):
    monkeypatch.setenv("HEALTHCHECK_PING_URL", URL)
    monkeypatch.delenv("HEALTHCHECK_RECAP_PING_URL", raising=False)
    assert ping_healthcheck.main(["--url-env", "HEALTHCHECK_RECAP_PING_URL"]) == 0
    assert network.calls == []
    assert "HEALTHCHECK_RECAP_PING_URL is not set" in capsys.readouterr().err


def test_strange_arguments_never_make_the_ping_fail(network, monkeypatch):
    monkeypatch.setenv("HEALTHCHECK_PING_URL", URL)
    assert ping_healthcheck.main(["--nonsense", "x", "-q"]) == 0
    assert [url for _, url, _ in network.calls] == [URL]
