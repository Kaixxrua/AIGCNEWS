"""Keep HTTPS certificate identity separate from the SSRF-pinned CONNECT IP."""
from __future__ import annotations

import ssl
import threading
import time

import certifi
import httpx

from backend.app.services.outbound_target_policy import is_safe_public_ip

ARTWORK_HOSTS = frozenset({
    "raw.githubusercontent.com", "github.com", "user-images.githubusercontent.com",
    "camo.githubusercontent.com", "avatars.githubusercontent.com",
})


class _ArtworkTLSContext(ssl.SSLContext):
    hostname: str

    def wrap_socket(self, *args, **kwargs):
        # httpcore's HTTP CONNECT path uses the origin IP as server_hostname,
        # ignoring request.extensions['sni_hostname']. Keep CONNECT pinned while
        # sending SNI and verifying the certificate against the allowlisted host.
        kwargs["server_hostname"] = self.hostname
        return super().wrap_socket(*args, **kwargs)


class GitHubArtworkTransport(httpx.BaseTransport):
    def __init__(self, proxy: str | None = None) -> None:
        self._proxy = proxy
        self._transports: dict[tuple[str, bool], httpx.HTTPTransport] = {}
        self._lock = threading.Lock()
        self._proxy_retry_at: dict[str, float] = {}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.extensions.get("sni_hostname")
        if (hostname not in ARTWORK_HOSTS or request.url.scheme != "https"
                or request.url.port not in (None, 443)
                or not is_safe_public_ip(request.url.host)
                or request.headers.get("host") != hostname):
            raise ValueError("artwork transport requires an allowlisted, pinned HTTPS target")
        with self._lock:
            cooling_down = self._proxy_retry_at.get(hostname, 0) > time.monotonic()
        if cooling_down:
            return self._transport(hostname, direct=True).handle_request(request)
        try:
            return self._transport(hostname, direct=False).handle_request(request)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            if not self._proxy or "CERTIFICATE_VERIFY_FAILED" in str(exc):
                raise
            with self._lock:
                self._proxy_retry_at[hostname] = time.monotonic() + 60
            # One bounded direct retry, retaining the exact validated IP and TLS
            # identity. A failing proxy must not leave the entire repair queue empty.
            return self._transport(hostname, direct=True).handle_request(request)

    def _transport(self, hostname: str, *, direct: bool) -> httpx.HTTPTransport:
        key = (hostname, direct)
        with self._lock:
            transport = self._transports.get(key)
            if transport is None:
                context = _ArtworkTLSContext(ssl.PROTOCOL_TLS_CLIENT)
                context.hostname = hostname
                context.load_verify_locations(certifi.where())
                transport = httpx.HTTPTransport(
                    verify=context, proxy=None if direct else self._proxy, trust_env=False,
                )
                self._transports[key] = transport
        return transport

    def close(self) -> None:
        for transport in self._transports.values():
            transport.close()
