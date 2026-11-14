"""An HTTP request that ends by a deadline, however slowly the server answers.

httpx's timeouts are per operation: each connect and each read may wait the whole
timeout, so a server that sends a few bytes just before every timeout runs out can
hold a request open long past an overall limit, and a check between chunks only
notices once the slow read has returned. transport() gives an httpx transport whose
every connect, TLS handshake, write and read waits at most the time left before
`deadline` (on `clock`), so the request ends by the deadline, give or take how long
the operating system takes to wake the waiting call. Name resolution is the
operating system's and is not capped here.

Used by the lookups (domain_lookup, telegram_lookup). Tests pass a fake `backend`
whose reads move a fake clock, so no network is touched.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpcore
import httpx

Clock = Callable[[], float]


class DeadlinePassed(Exception):
    """The deadline came before the server finished. Not an httpx error, so a caller can
    tell a slow server from an unreachable one."""


def _capped(deadline: float, clock: Clock, timeout: float | None, call: Callable[..., Any],
            *args: Any, **kwargs: Any) -> Any:
    """call(*args, timeout=...), waiting no longer than `timeout` or the time left, whichever is less."""
    left = deadline - clock()
    if left <= 0:
        raise DeadlinePassed()
    binding = timeout is None or left <= timeout
    try:
        return call(*args, timeout=left if binding else timeout, **kwargs)
    except httpcore.TimeoutException as exc:
        if binding:
            raise DeadlinePassed() from exc
        raise


class _Stream(httpcore.NetworkStream):
    def __init__(self, inner: httpcore.NetworkStream, deadline: float, clock: Clock) -> None:
        self._inner, self._deadline, self._clock = inner, deadline, clock

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return _capped(self._deadline, self._clock, timeout, self._inner.read, max_bytes)

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        _capped(self._deadline, self._clock, timeout, self._inner.write, buffer)

    def close(self) -> None:
        self._inner.close()

    def start_tls(self, ssl_context: Any, server_hostname: str | None = None,
                  timeout: float | None = None) -> httpcore.NetworkStream:
        inner = _capped(self._deadline, self._clock, timeout, self._inner.start_tls, ssl_context, server_hostname)
        return _Stream(inner, self._deadline, self._clock)

    def get_extra_info(self, info: str) -> Any:
        return self._inner.get_extra_info(info)


class _Backend(httpcore.NetworkBackend):
    def __init__(self, inner: httpcore.NetworkBackend, deadline: float, clock: Clock) -> None:
        self._inner, self._deadline, self._clock = inner, deadline, clock

    def connect_tcp(self, host: str, port: int, timeout: float | None = None, local_address: str | None = None,
                    socket_options: Any = None) -> httpcore.NetworkStream:
        stream = _capped(self._deadline, self._clock, timeout, self._inner.connect_tcp, host, port,
                         local_address=local_address, socket_options=socket_options)
        return _Stream(stream, self._deadline, self._clock)

    def connect_unix_socket(self, path: str, timeout: float | None = None,
                            socket_options: Any = None) -> httpcore.NetworkStream:
        stream = _capped(self._deadline, self._clock, timeout, self._inner.connect_unix_socket, path,
                         socket_options=socket_options)
        return _Stream(stream, self._deadline, self._clock)

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


def transport(deadline: float, clock: Clock, backend: httpcore.NetworkBackend | None = None) -> httpx.HTTPTransport:
    """httpx's own transport (certificates checked, HTTP/1.1, no retries, no proxy), its
    connections made through a backend that caps every wait at the time left before `deadline`."""
    made = httpx.HTTPTransport()
    made._pool = httpcore.ConnectionPool(  # httpx 0.28 takes no network backend, so its pool is swapped
        ssl_context=httpx.create_ssl_context(), retries=0,
        network_backend=_Backend(backend or httpcore.SyncBackend(), deadline, clock))
    return made
