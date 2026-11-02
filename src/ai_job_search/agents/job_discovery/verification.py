from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlsplit

from pydantic import HttpUrl

VerificationStatus = Literal["verified", "expired", "unavailable"]


@dataclass(frozen=True)
class URLVerification:
    status: VerificationStatus
    http_status: int | None
    final_url: str | None
    evidence: str


class SafePostingURLVerifier:
    def __init__(
        self,
        *,
        timeout_seconds: float = 4,
        max_redirects: int = 4,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_redirects = max_redirects
        self._ssl_context = ssl.create_default_context()

    def verify(self, url: HttpUrl) -> URLVerification:
        current_url = str(url)
        for _ in range(self._max_redirects + 1):
            try:
                status, redirect_url = self._request(current_url, "HEAD")
                if status in {405, 501}:
                    status, redirect_url = self._request(current_url, "GET")
            except (
                http.client.HTTPException,
                OSError,
                TimeoutError,
                ValueError,
            ):
                return URLVerification(
                    status="unavailable",
                    http_status=None,
                    final_url=current_url,
                    evidence="The public HTTPS URL could not be reached safely.",
                )

            if 300 <= status < 400 and redirect_url:
                current_url = urljoin(current_url, redirect_url)
                continue
            if 200 <= status < 300:
                return URLVerification(
                    status="verified",
                    http_status=status,
                    final_url=current_url,
                    evidence="The URL returned a successful HTTPS response.",
                )
            if status == 410:
                return URLVerification(
                    status="expired",
                    http_status=status,
                    final_url=current_url,
                    evidence="The URL returned HTTP 410 Gone.",
                )
            return URLVerification(
                status="unavailable",
                http_status=status,
                final_url=current_url,
                evidence=f"The URL returned HTTP {status}.",
            )

        return URLVerification(
            status="unavailable",
            http_status=None,
            final_url=current_url,
            evidence="The URL exceeded the allowed HTTPS redirect limit.",
        )

    def _request(self, url: str, method: Literal["HEAD", "GET"]) -> tuple[int, str | None]:
        parsed = urlsplit(url)
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        ):
            raise ValueError("Only public HTTPS URLs on port 443 can be verified.")

        host = parsed.hostname
        addresses = socket.getaddrinfo(
            host,
            443,
            type=socket.SOCK_STREAM,
        )
        public_addresses = []
        for family, socktype, protocol, _, address in addresses:
            ip = ipaddress.ip_address(address[0].split("%", 1)[0])
            if not ip.is_global:
                raise ValueError("The URL resolved to a non-public network address.")
            public_addresses.append((family, socktype, protocol, address))
        if not public_addresses:
            raise OSError("The URL hostname did not resolve.")

        family, socktype, protocol, address = public_addresses[0]
        sock = socket.socket(family, socktype, protocol)
        tls_socket: ssl.SSLSocket | None = None
        try:
            sock.settimeout(self._timeout_seconds)
            sock.connect(address)
            tls_socket = self._ssl_context.wrap_socket(
                sock,
                server_hostname=host,
            )
            request_target = parsed.path or "/"
            if parsed.query:
                request_target = f"{request_target}?{parsed.query}"
            host_header = f"[{host}]" if ":" in host else host
            tls_socket.sendall(
                (
                    f"{method} {request_target} HTTP/1.1\r\n"
                    f"Host: {host_header}\r\n"
                    "User-Agent: AIJobSearch-URL-Check/1.0\r\n"
                    "Accept: text/html,application/xhtml+xml\r\n"
                    "Range: bytes=0-0\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
            )
            response = http.client.HTTPResponse(tls_socket)
            response.begin()
            return response.status, response.getheader("Location")
        finally:
            if tls_socket is not None:
                tls_socket.close()
            else:
                sock.close()
