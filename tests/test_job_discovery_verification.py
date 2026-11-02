import socket

from pydantic import HttpUrl

from ai_job_search.agents.job_discovery.verification import (
    SafePostingURLVerifier,
)


def test_verifies_successful_url_after_redirect(monkeypatch) -> None:
    verifier = SafePostingURLVerifier()
    requests = []

    def fake_request(url: str, method: str) -> tuple[int, str | None]:
        requests.append((url, method))
        if len(requests) == 1:
            return 302, "https://careers.example/open-role"
        return 200, None

    monkeypatch.setattr(verifier, "_request", fake_request)
    result = verifier.verify(HttpUrl("https://jobs.example/role"))

    assert result.status == "reachable"
    assert result.http_status == 200
    assert result.final_url == "https://careers.example/open-role"
    assert requests == [
        ("https://jobs.example/role", "HEAD"),
        ("https://careers.example/open-role", "HEAD"),
    ]


def test_head_not_supported_falls_back_to_bounded_get(monkeypatch) -> None:
    verifier = SafePostingURLVerifier()
    methods = []

    def fake_request(url: str, method: str) -> tuple[int, str | None]:
        methods.append(method)
        return (405, None) if method == "HEAD" else (206, None)

    monkeypatch.setattr(verifier, "_request", fake_request)
    result = verifier.verify(HttpUrl("https://jobs.example/role"))

    assert result.status == "reachable"
    assert methods == ["HEAD", "GET"]


def test_http_410_is_marked_expired(monkeypatch) -> None:
    verifier = SafePostingURLVerifier()
    monkeypatch.setattr(
        verifier,
        "_request",
        lambda url, method: (410, None),
    )

    result = verifier.verify(HttpUrl("https://jobs.example/role"))

    assert result.status == "expired"
    assert result.http_status == 410


def test_private_dns_resolution_is_rejected_before_connect(monkeypatch) -> None:
    verifier = SafePostingURLVerifier()
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("127.0.0.1", 443),
            )
        ],
    )

    def forbidden_socket(*args, **kwargs):
        raise AssertionError("Private destinations must not be connected")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    result = verifier.verify(HttpUrl("https://internal.example/"))

    assert result.status == "unavailable"
    assert result.http_status is None


def test_http_redirect_is_not_followed(monkeypatch) -> None:
    verifier = SafePostingURLVerifier()
    requests = []
    actual_request = verifier._request

    def fake_first_request(url: str, method: str) -> tuple[int, str | None]:
        requests.append(url)
        if len(requests) == 1:
            return 301, "http://127.0.0.1/admin"
        return actual_request(url, method)

    monkeypatch.setattr(verifier, "_request", fake_first_request)
    result = verifier.verify(HttpUrl("https://jobs.example/role"))

    assert result.status == "unavailable"
    assert requests == [
        "https://jobs.example/role",
        "http://127.0.0.1/admin",
    ]


def test_redirect_loop_stops_at_configured_limit(monkeypatch) -> None:
    verifier = SafePostingURLVerifier(max_redirects=2)
    requests = []

    def fake_request(url: str, method: str) -> tuple[int, str | None]:
        requests.append(url)
        return 302, "/redirect"

    monkeypatch.setattr(verifier, "_request", fake_request)
    result = verifier.verify(HttpUrl("https://jobs.example/role"))

    assert result.status == "unavailable"
    assert len(requests) == 3
