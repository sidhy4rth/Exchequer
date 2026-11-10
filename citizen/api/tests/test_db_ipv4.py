"""The citizen functions connect to Neon's IPv4 address too (see the main
app's tests/test_db_ipv4.py): a host that resolves to IPv6 first must not
leave the site unable to take complaints."""
import socket

from _lib import db

NEON = "ep-quiet-sky-123-pooler.ap-southeast-1.aws.neon.tech"
URL = f"postgresql://exchequer_citizen:pw@{NEON}/neondb?sslmode=require"


def resolver(table):
    def resolve(host, port, family, kind):
        if host in table:
            return [(socket.AF_INET, kind, 6, "", (table[host], port))]
        raise socket.gaierror(socket.EAI_NONAME, "no IPv4 address")
    return resolve


def test_the_citizen_connection_uses_the_ipv4_address():
    assert db.ipv4_hostaddr(URL, resolve=resolver({NEON: "13.228.46.236"})) == {"hostaddr": "13.228.46.236"}


def test_no_ipv4_address_or_an_ip_host_adds_nothing():
    assert db.ipv4_hostaddr(URL, resolve=resolver({})) == {}
    assert db.ipv4_hostaddr("postgresql://u:p@13.228.46.236/neondb", resolve=resolver({})) == {}


def test_the_switch_turns_it_off(monkeypatch):
    monkeypatch.setenv("CITIZEN_DB_PREFER_IPV4", "0")
    assert db.ipv4_hostaddr(URL, resolve=resolver({NEON: "13.228.46.236"})) == {}
