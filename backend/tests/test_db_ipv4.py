"""Render's free instances cannot open IPv6 connections, and Neon's hosts
answer with both IPv6 and IPv4 addresses: the driver tried IPv6 and the store
stayed unreachable ("Network is unreachable"). The engine now connects to the
host's IPv4 address, keeping the name for TLS and Neon's routing."""
import socket

import pytest
from sqlalchemy import create_engine, event

from app import config, models

NEON = "ep-quiet-sky-123.ap-southeast-1.aws.neon.tech"


def resolver(table):
    def resolve(host, port, family, kind):
        assert family == socket.AF_INET
        if host in table:
            return [(socket.AF_INET, kind, 6, "", (table[host], port))]
        raise socket.gaierror(socket.EAI_NONAME, "no IPv4 address")
    return resolve


def test_a_named_host_connects_to_its_ipv4_address_and_keeps_its_name():
    cparams = {"host": NEON, "port": 5432, "dbname": "neondb"}
    models.prefer_ipv4(cparams, resolve=resolver({NEON: "13.228.46.236"}))
    assert cparams["hostaddr"] == "13.228.46.236"
    assert cparams["host"] == NEON


@pytest.mark.parametrize("host", ["13.228.46.236", "2406:da18:94d:820a::1", "/var/run/postgresql", "a.example,b.example"])
def test_addresses_sockets_and_host_lists_are_left_alone(host):
    cparams = {"host": host}
    models.prefer_ipv4(cparams, resolve=resolver({host: "1.2.3.4"}))
    assert "hostaddr" not in cparams


def test_a_host_with_no_ipv4_address_is_left_to_the_driver():
    cparams = {"host": NEON}
    models.prefer_ipv4(cparams, resolve=resolver({}))
    assert "hostaddr" not in cparams


def test_an_explicit_hostaddr_wins():
    cparams = {"host": NEON, "hostaddr": "10.0.0.9"}
    models.prefer_ipv4(cparams, resolve=resolver({NEON: "13.228.46.236"}))
    assert cparams["hostaddr"] == "10.0.0.9"


def test_the_switch_turns_it_off(monkeypatch):
    monkeypatch.setattr(config, "DB_PREFER_IPV4", False)
    cparams = {"host": NEON}
    models.prefer_ipv4(cparams, resolve=resolver({NEON: "13.228.46.236"}))
    assert "hostaddr" not in cparams


def test_the_postgres_engine_resolves_on_every_connect():
    engine = models.postgres_engine("postgresql+psycopg://u:p@" + NEON + "/neondb?sslmode=require")
    assert event.contains(engine, "do_connect", models._prefer_ipv4_on_connect)
    assert not event.contains(create_engine("sqlite://"), "do_connect", models._prefer_ipv4_on_connect)
