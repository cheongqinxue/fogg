"""Small fail-closed HTTP forward proxy for an isolated browser worker.

The proxy accepts one HTTP request per client connection. HTTPS is supported via
CONNECT and becomes an opaque byte tunnel after destination validation.

Public-address validation does not prevent access to services exposed on the
host's public IP. Deployments must deny those addresses in
``BROWSER_PROXY_DENY_HOSTS`` or enforce an external egress policy.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import socket
from http import HTTPStatus
from dataclasses import dataclass
from typing import Any

import h11
from yarl import URL

logger = logging.getLogger("browser_proxy")

HEADER_LIMIT = 32 * 1024
BODY_LIMIT = 16 * 1024 * 1024
RESPONSE_LIMIT = 64 * 1024 * 1024
CONNECT_TIMEOUT = 8.0
IDLE_TIMEOUT = 30.0
MAX_CONNECTIONS = 64
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
_DEFAULT_DENY = {"metadata.google.internal", "metadata.google", "instance-data.ec2.internal"}


class ProxyError(ValueError):
    """Invalid or forbidden proxy request."""


@dataclass(frozen=True)
class Destination:
    host: str
    port: int
    scheme: str


def validate_deny_hosts(configured: str | None = None) -> set[str]:
    """Validate and normalize configured host, IP, and CIDR denylist entries.

    An unset or empty value is valid for library callers. Deployments should
    configure infrastructure-specific addresses in addition to the defaults.
    """
    if configured is None:
        configured = os.getenv("BROWSER_PROXY_DENY_HOSTS", "")
    if not configured.strip():
        return set(_DEFAULT_DENY)

    entries = configured.split(",")
    if any(not item.strip() for item in entries):
        raise ValueError("BROWSER_PROXY_DENY_HOSTS contains an empty entry")

    normalized: set[str] = set(_DEFAULT_DENY)
    for item in entries:
        entry = item.strip().lower().rstrip(".")
        try:
            if "/" in entry:
                normalized.add(str(ipaddress.ip_network(entry, strict=False)))
            else:
                try:
                    normalized.add(ipaddress.ip_address(entry).compressed)
                except ValueError:
                    normalized.add(_normalize_host(entry))
        except ValueError as exc:
            raise ValueError("BROWSER_PROXY_DENY_HOSTS contains an invalid entry") from exc
    return normalized


def _deny_hosts() -> set[str]:
    return validate_deny_hosts()


def _normalize_host(host: str) -> str:
    host = host.rstrip(".").lower()
    if not host or "%" in host:
        raise ProxyError("invalid host")
    try:
        return ipaddress.ip_address(host).compressed
    except ValueError:
        pass
    if not _HOST_RE.fullmatch(host):
        raise ProxyError("invalid host")
    try:
        encoded = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ProxyError("invalid host") from exc
    if len(encoded) > 253 or any(not label or len(label) > 63 for label in encoded.split(".")):
        raise ProxyError("invalid host")
    return encoded


def parse_authority(authority: str, *, scheme: str) -> Destination:
    """Parse CONNECT authority or an absolute HTTP URL, rejecting ambiguity."""
    if not authority or any(ord(ch) < 33 or ord(ch) == 127 for ch in authority):
        raise ProxyError("invalid authority")
    if scheme == "connect":
        # Bracketed IPv6 only; reject userinfo, paths, and unbracketed IPv6.
        if authority.startswith("["):
            close = authority.find("]")
            if close < 0 or close + 1 >= len(authority) or authority[close + 1] != ":":
                raise ProxyError("invalid CONNECT authority")
            host, raw_port = authority[1:close], authority[close + 2 :]
            try:
                ipaddress.IPv6Address(host)
            except ValueError as exc:
                raise ProxyError("invalid CONNECT authority") from exc
        else:
            if authority.count(":") != 1:
                raise ProxyError("invalid CONNECT authority")
            host, raw_port = authority.rsplit(":", 1)
        if not raw_port.isascii() or not raw_port.isdecimal():
            raise ProxyError("invalid port")
        port = int(raw_port)
        if port != 443:
            raise ProxyError("CONNECT port forbidden")
        return Destination(_normalize_host(host), port, "https")

    try:
        url = URL(authority, encoded=False)
    except (TypeError, ValueError) as exc:
        raise ProxyError("invalid request URL") from exc
    if url.scheme != "http" or not url.is_absolute() or url.raw_host is None:
        raise ProxyError("only absolute http URLs are accepted")
    if url.user is not None or url.password is not None or url.fragment:
        raise ProxyError("credentials and fragments are forbidden")
    if url.port not in (None, 80):
        raise ProxyError("HTTP port forbidden")
    return Destination(_normalize_host(url.raw_host), 80, "http")


def _is_denied_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address, deny: set[str]) -> bool:
    addresses = [address]
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        addresses.append(address.ipv4_mapped)
    for entry in deny:
        try:
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
                if any(
                    candidate.version == network.version and candidate in network
                    for candidate in addresses
                ):
                    return True
            else:
                denied = ipaddress.ip_address(entry)
                if any(candidate == denied for candidate in addresses):
                    return True
        except ValueError:
            continue
    return False


def _check_host_policy(host: str) -> None:
    deny = _deny_hosts()
    if host.lower().rstrip(".") in deny:
        raise ProxyError("host is denied")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global or _is_denied_ip(address, deny):
        raise ProxyError("non-public IP address")


async def resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    """Resolve once; reject the entire result if any address is non-public."""
    _check_host_policy(host)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        values = (literal.compressed,)
    else:
        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(
                loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=CONNECT_TIMEOUT
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise ProxyError("DNS resolution failed") from exc
        values = tuple(dict.fromkeys(info[4][0] for info in infos))
    if not values:
        raise ProxyError("DNS returned no addresses")
    parsed = []
    for value in values:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ProxyError("DNS returned invalid address") from exc
        if not address.is_global or _is_denied_ip(address, _deny_hosts()):
            raise ProxyError("DNS returned a non-public address")
        parsed.append(address.compressed)
    return tuple(parsed)


async def open_validated_connection(
    host: str, port: int
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect to a validated literal IP, preventing a second DNS lookup."""
    addresses = await resolve_public_addresses(host, port)
    errors: list[OSError] = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        try:
            return await asyncio.wait_for(
                asyncio.open_connection(address, port, family=family), timeout=CONNECT_TIMEOUT
            )
        except (OSError, asyncio.TimeoutError) as exc:
            if isinstance(exc, OSError):
                errors.append(exc)
    raise ProxyError("connection failed") from (errors[-1] if errors else None)


async def _read_event(conn: h11.Connection, reader: asyncio.StreamReader) -> Any:
    while True:
        event = conn.next_event()
        if event is not h11.NEED_DATA:
            return event
        data = await asyncio.wait_for(reader.read(16 * 1024), timeout=IDLE_TIMEOUT)
        if not data:
            conn.receive_data(b"")
        else:
            conn.receive_data(data)


async def _write_error(writer: asyncio.StreamWriter, status: int, message: str) -> None:
    body = (message + "\n").encode("ascii", "replace")
    writer.write(
        f"HTTP/1.1 {status} {HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else 'Error'}\r\n"
        f"Connection: close\r\nContent-Length: {len(body)}\r\n"
        "Content-Type: text/plain\r\n\r\n".encode("ascii")
        + body
    )
    await writer.drain()


def _headers(event: h11.Request) -> list[tuple[bytes, bytes]]:
    headers = [(k.lower(), v) for k, v in event.headers]
    connection_tokens = set()
    for key, value in headers:
        if key == b"connection":
            connection_tokens.update(token.strip().lower() for token in value.split(b","))
    blocked = {
        b"proxy-authorization",
        b"proxy-connection",
        b"connection",
        b"keep-alive",
        b"host",
    } | connection_tokens
    return [(key, value) for key, value in headers if key not in blocked]


async def _tunnel(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    remote_reader: asyncio.StreamReader,
    remote_writer: asyncio.StreamWriter,
) -> None:
    async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        total = 0
        while data := await asyncio.wait_for(src.read(64 * 1024), timeout=IDLE_TIMEOUT):
            total += len(data)
            if total > RESPONSE_LIMIT:
                return
            dst.write(data)
            await dst.drain()
        try:
            dst.write_eof()
        except (AttributeError, OSError):
            pass

    tasks = [
        asyncio.create_task(pump(client_reader, remote_writer)),
        asyncio.create_task(pump(remote_reader, client_writer)),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, *pending, return_exceptions=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    remote_writer: asyncio.StreamWriter | None = None
    try:
        conn = h11.Connection(h11.SERVER, max_incomplete_event_size=HEADER_LIMIT)
        event = await _read_event(conn, reader)
        if not isinstance(event, h11.Request):
            raise ProxyError("expected HTTP request")
        method = event.method.upper()
        if method == b"CONNECT":
            destination = parse_authority(event.target.decode("ascii"), scheme="connect")
            remote_reader, remote_writer = await open_validated_connection(
                destination.host, destination.port
            )
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            # h11 may have buffered early tunnel bytes; put them back into client stream is not supported.
            buffered = conn.trailing_data[0]
            if buffered:
                remote_writer.write(buffered)
                await remote_writer.drain()
            await _tunnel(reader, writer, remote_reader, remote_writer)
            return

        destination = parse_authority(event.target.decode("ascii"), scheme="http")
        if method not in {b"GET", b"HEAD", b"OPTIONS"}:
            raise ProxyError("HTTP method forbidden")
        _check_host_policy(destination.host)
        remote_reader, remote_writer = await open_validated_connection(
            destination.host, destination.port
        )
        out = h11.Connection(h11.CLIENT, max_incomplete_event_size=HEADER_LIMIT)
        target_url = URL(event.target.decode("ascii"))
        path = target_url.raw_path_qs or "/"
        headers = _headers(event) + [(b"host", destination.host.encode("ascii"))]
        remote_writer.write(
            out.send(h11.Request(method=event.method, target=path.encode("ascii"), headers=headers))
        )
        await remote_writer.drain()

        body_sent = 0
        while True:
            item = await _read_event(conn, reader)
            if isinstance(item, h11.Data):
                body_sent += len(item.data)
                if body_sent > BODY_LIMIT:
                    raise ProxyError("request body too large")
                remote_writer.write(out.send(item))
                await remote_writer.drain()
            elif isinstance(item, h11.EndOfMessage):
                remote_writer.write(out.send(item))
                await remote_writer.drain()
                break
            else:
                raise ProxyError("unsupported request framing")

        response_size = 0
        response_conn = h11.Connection(h11.SERVER, max_incomplete_event_size=HEADER_LIMIT)
        while True:
            item = await _read_event(out, remote_reader)
            if isinstance(item, h11.Data):
                response_size += len(item.data)
                if response_size > RESPONSE_LIMIT:
                    raise ProxyError("response too large")
                writer.write(response_conn.send(item))
                await writer.drain()
            elif isinstance(item, (h11.Response, h11.InformationalResponse)):
                writer.write(response_conn.send(item))
                await writer.drain()
            elif isinstance(item, h11.EndOfMessage):
                writer.write(response_conn.send(item))
                await writer.drain()
                break
            elif item is h11.PAUSED:
                break
            else:
                raise ProxyError("invalid upstream response")
    except (ProxyError, h11.ProtocolError, UnicodeError, asyncio.TimeoutError, OSError) as exc:
        status = 413 if str(exc) in {"request body too large", "response too large"} else 400
        try:
            await _write_error(writer, status, "proxy request rejected")
        except (ConnectionError, OSError):
            pass
        # Deliberately never log URL, headers, or exception text.
        logger.info("proxy connection rejected (%s)", type(exc).__name__)
    finally:
        if remote_writer is not None:
            remote_writer.close()
            try:
                await remote_writer.wait_closed()
            except OSError:
                pass
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def run_proxy(socket_path: str = "/run/browser-proxy/proxy.sock") -> None:
    """Run the proxy on a Unix-domain socket for isolated worker containers."""
    validate_deny_hosts()
    path = os.path.abspath(socket_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    limit = int(os.getenv("BROWSER_PROXY_MAX_CONNECTIONS", str(MAX_CONNECTIONS)))
    if limit < 1 or limit > 1024:
        raise ValueError("BROWSER_PROXY_MAX_CONNECTIONS must be between 1 and 1024")
    active = 0
    active_lock = asyncio.Lock()

    async def guarded(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal active
        async with active_lock:
            if active >= limit:
                await _write_error(writer, 503, "proxy busy")
                writer.close()
                return
            active += 1
        try:
            await _handle(reader, writer)
        finally:
            async with active_lock:
                active -= 1

    server = await asyncio.start_unix_server(guarded, path=path, limit=HEADER_LIMIT + 1)
    os.chmod(path, 0o660)
    async with server:
        await server.serve_forever()


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "WARNING"))
    socket_path = os.getenv("BROWSER_PROXY_SOCKET_PATH", "/run/browser-proxy/proxy.sock")
    asyncio.run(run_proxy(socket_path))


if __name__ == "__main__":
    main()
