"""Offline security and protocol checks for the browser's egress proxy."""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import pytest

from browser_proxy import server


@pytest.mark.parametrize(
    ("target", "scheme"),
    [
        ("localhost:6379", "connect"),
        ("example.com:80", "connect"),
        ("user@example.com:443", "connect"),
        ("example.com:443/path", "connect"),
        ("http://user:secret@example.com/", "http"),
        ("http://example.com:8080/", "http"),
        ("http://example.com/#fragment", "http"),
    ],
)
def test_rejects_ambiguous_or_disallowed_authorities(target: str, scheme: str) -> None:
    with pytest.raises(server.ProxyError):
        server.parse_authority(target, scheme=scheme)


@pytest.mark.parametrize("configured", ["example.test,", "93.184.216.0/99", "bad host"])
def test_invalid_deployment_denylist_fails_closed(configured: str) -> None:
    with pytest.raises(ValueError):
        server.validate_deny_hosts(configured)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"]
)
async def test_rejects_nonpublic_literal_addresses(host: str) -> None:
    with pytest.raises(server.ProxyError):
        await server.resolve_public_addresses(host, 443)


@pytest.mark.asyncio
async def test_rejects_mixed_public_and_private_dns_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()

    async def resolve(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    with pytest.raises(server.ProxyError):
        await server.resolve_public_addresses("example.test", 443)


@pytest.mark.asyncio
async def test_rejects_dns_answer_in_configured_infrastructure_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setenv("BROWSER_PROXY_DENY_HOSTS", "93.184.216.0/24")

    async def resolve(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    with pytest.raises(server.ProxyError):
        await server.resolve_public_addresses("example.test", 443)


@pytest.mark.asyncio
async def test_connection_uses_the_validated_address_without_resolving_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    lookups = []
    connections = []

    async def resolve(host: str, port: int, **_kwargs: Any) -> list[Any]:
        lookups.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    async def connect(host: str, port: int, **_kwargs: Any) -> tuple[object, object]:
        connections.append((host, port))
        return object(), object()

    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    monkeypatch.setattr(asyncio, "open_connection", connect)
    await server.open_validated_connection("example.test", 443)
    assert lookups == ["example.test"]
    assert connections == [("93.184.216.34", 443)]


class MemoryWriter:
    """Capture proxy output without opening sockets."""

    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


def reader_with(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


@pytest.mark.asyncio
async def test_http_proxy_forwards_valid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream = MemoryWriter()

    async def connect(host: str, port: int) -> tuple[asyncio.StreamReader, MemoryWriter]:
        assert (host, port) == ("example.test", 80)
        return reader_with(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"), upstream

    monkeypatch.setattr(server, "open_validated_connection", connect)
    client = MemoryWriter()
    await server._handle(
        reader_with(b"GET http://example.test/path HTTP/1.1\r\nHost: example.test\r\n\r\n"), client
    )
    assert bytes(client.data).startswith(b"HTTP/1.1 200")
    assert bytes(client.data).endswith(b"OK")
    assert b"GET /path HTTP/1.1" in upstream.data


@pytest.mark.asyncio
async def test_http_proxy_rejects_mutating_methods_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbidden_connect(*_args: object) -> None:
        pytest.fail("a mutating HTTP request must not reach an upstream")

    monkeypatch.setattr(server, "open_validated_connection", forbidden_connect)
    client = MemoryWriter()
    await server._handle(
        reader_with(
            b"POST http://example.test/ HTTP/1.1\r\nHost: example.test\r\nContent-Length: 0\r\n\r\n"
        ),
        client,
    )
    assert bytes(client.data).startswith((b"HTTP/1.1 400", b"HTTP/1.1 403", b"HTTP/1.1 405"))


@pytest.mark.asyncio
async def test_connect_checks_dns_once_then_tunnels_to_validated_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    lookups = []
    connections = []
    upstream = MemoryWriter()

    async def resolve(host: str, port: int, **_kwargs: Any) -> list[Any]:
        lookups.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    async def connect(
        host: str, port: int, **_kwargs: Any
    ) -> tuple[asyncio.StreamReader, MemoryWriter]:
        connections.append((host, port))
        return reader_with(b""), upstream

    async def tunnel(*_args: object) -> None:
        pass

    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    monkeypatch.setattr(asyncio, "open_connection", connect)
    monkeypatch.setattr(server, "_tunnel", tunnel)
    client = MemoryWriter()
    await server._handle(
        reader_with(b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n\r\n"),
        client,
    )
    assert lookups == ["example.test"]
    assert connections == [("93.184.216.34", 443)]
    assert bytes(client.data).startswith(b"HTTP/1.1 200")
