"""http_deadline: every connect and read of a request waits at most the time left before
its deadline, so a slow server cannot hold the request past it. A fake network moves a
fake clock instead of waiting; nothing touches the network."""
import httpcore
import httpx
import pytest

from app import http_deadline

RESPONSE = b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n"


class SlowNetwork(httpcore.NetworkBackend):
    """A server that takes `connect_s` to accept and then sends one piece every `gap_s`
    seconds. A wait shorter than the server's next delay times out, as a socket would."""

    def __init__(self, now: list[float], pieces: list[bytes], gap_s: float, connect_s: float = 0.0):
        self.now, self.pieces, self.gap_s, self.connect_s = now, list(pieces), gap_s, connect_s
        self.waits: list[tuple[str, float | None]] = []  # (operation, timeout it was given)

    def _wait(self, what: str, needs: float, timeout: float | None, error: type[Exception]) -> None:
        self.waits.append((what, timeout))
        if timeout is not None and needs > timeout:
            self.now[0] += timeout
            raise error("timed out")
        self.now[0] += needs

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self._wait("connect", self.connect_s, timeout, httpcore.ConnectTimeout)
        return _FakeStream(self)

    def connect_unix_socket(self, path, timeout=None, socket_options=None):  # pragma: no cover
        raise NotImplementedError

    def sleep(self, seconds):  # pragma: no cover
        self.now[0] += seconds


class _FakeStream(httpcore.NetworkStream):
    def __init__(self, net: SlowNetwork):
        self.net = net

    def read(self, max_bytes, timeout=None):
        if not self.net.pieces:
            return b""
        self.net._wait("read", self.net.gap_s, timeout, httpcore.ReadTimeout)
        return self.net.pieces.pop(0)

    def write(self, buffer, timeout=None):
        self.net.waits.append(("write", timeout))

    def close(self):
        pass

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.net.waits.append(("tls", timeout))
        return self

    def get_extra_info(self, info):
        return None


def _fetch(net: SlowNetwork, deadline: float, timeout: float = 8.0) -> bytes:
    clock = lambda: net.now[0]  # noqa: E731
    with httpx.Client(timeout=timeout, transport=http_deadline.transport(deadline, clock, net)) as client:
        with client.stream("GET", "https://example.test/") as response:
            return b"".join(response.iter_bytes())


def test_httpx_still_has_the_private_pool_that_transport_swaps():
    """transport() replaces httpx.HTTPTransport._pool (private; httpx and httpcore are pinned). If an
    upgrade renames it, this fails here rather than leaving lookups silently uncapped."""
    assert isinstance(httpx.HTTPTransport()._pool, httpcore.ConnectionPool)
    pool = http_deadline.transport(10.0, lambda: 0.0)._pool
    assert isinstance(pool, httpcore.ConnectionPool)
    assert isinstance(pool._network_backend, http_deadline._Backend)


def test_transport_refuses_to_run_uncapped_if_the_pool_is_gone(monkeypatch):
    class NoPool(httpx.BaseTransport):
        pass
    monkeypatch.setattr(http_deadline.httpx, "HTTPTransport", NoPool)
    with pytest.raises(RuntimeError, match="_pool"):
        http_deadline.transport(10.0, lambda: 0.0)


def test_a_prompt_server_is_read_whole_and_waits_keep_their_own_timeout():
    net = SlowNetwork([0.0], [RESPONSE, b"0123456789"], gap_s=1.0)
    assert _fetch(net, deadline=15.0) == b"0123456789"
    assert {t for _, t in net.waits} == {8.0}  # 15 s left at every wait, so the 8 s timeout stands


def test_a_server_sending_just_inside_each_timeout_stops_at_the_deadline():
    """7 s per piece is inside the 8 s read timeout, so httpx alone would wait 7 s per piece for ever."""
    net = SlowNetwork([0.0], [RESPONSE] + [b"0"] * 10, gap_s=7.0)
    with pytest.raises(http_deadline.DeadlinePassed):
        _fetch(net, deadline=15.0)
    assert net.now[0] == pytest.approx(15.0)
    assert [t for w, t in net.waits if w == "read"] == [8.0, 8.0, pytest.approx(1.0)]


def test_a_slow_connect_is_capped_at_the_time_left():
    net = SlowNetwork([0.0], [RESPONSE], gap_s=0.0, connect_s=20.0)
    with pytest.raises(http_deadline.DeadlinePassed):
        _fetch(net, deadline=5.0)
    assert net.waits == [("connect", 5.0)] and net.now[0] == pytest.approx(5.0)


def test_a_timeout_shorter_than_the_time_left_is_still_an_httpx_timeout():
    """Only the deadline's own cut is DeadlinePassed; a server silent past TIMEOUT_S is a plain timeout."""
    net = SlowNetwork([0.0], [RESPONSE, b"0"], gap_s=9.0)
    with pytest.raises(httpx.ReadTimeout):
        _fetch(net, deadline=30.0)


def test_nothing_is_attempted_once_the_deadline_has_passed():
    net = SlowNetwork([10.0], [RESPONSE], gap_s=0.0)
    with pytest.raises(http_deadline.DeadlinePassed):
        _fetch(net, deadline=5.0)
    assert net.waits == []
