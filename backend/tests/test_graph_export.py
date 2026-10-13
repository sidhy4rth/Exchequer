"""Graph export (app/graph_export.py): GraphML other tools open, CSV a spreadsheet opens."""
from __future__ import annotations

import csv
import io

import networkx as nx

from app import graph_export

RESULT = {
    "address": "0xseed", "chain": "ethereum", "asset": "ETH",
    "trace_path": [{"address": "0xseed"}, {"address": "0xmid"}, {"address": "0xbin"}],
    "graph": {
        "nodes": [
            {"id": "0xseed", "depth": 0, "is_seed": True, "flags": []},
            {"id": "0xmid", "depth": 1, "label": "=HYPERLINK(\"http://x\")", "flags": ["amount_split"]},
            {"id": "0xbin", "depth": 2, "exchange": "Binance", "label": "Binance 14 <hot> & co",
             "total_in_native": 9.5},
        ],
        "edges": [
            {"source": "0xseed", "target": "0xmid", "value_native": 10.0, "tx_count": 1,
             "first_seen": 1630423444, "last_seen": 1630423444, "flags": []},
            {"source": "0xmid", "target": "0xbin", "value_native": 9.5, "tx_count": 2, "flags": []},
        ],
    },
}


def test_graphml_loads_in_networkx_with_attributes():
    text = graph_export.to_graphml("abcd1234", RESULT)
    g = nx.read_graphml(io.BytesIO(text.encode()))
    assert g.number_of_nodes() == 3 and g.number_of_edges() == 2
    assert g.nodes["0xbin"]["exchange"] == "Binance"
    assert g.nodes["0xbin"]["label"] == "Binance 14 <hot> & co"  # escaped, round-trips
    assert g.nodes["0xseed"]["role"] == "reported"
    assert g.edges["0xseed", "0xmid"]["on_principal_path"] is True
    assert g.edges["0xseed", "0xmid"]["first_seen"].startswith("2021-08-31")


def test_csv_has_both_tables_and_defuses_formulas():
    text = graph_export.to_csv("abcd1234", RESULT)
    rows = list(csv.reader(io.StringIO(text)))
    assert ["# addresses"] in rows and ["# transfers"] in rows
    addresses = rows[rows.index(["# addresses"]) + 2:rows.index(["# transfers"])]
    labels = [r[3] for r in addresses if r and r[0] == "0xmid"]
    assert labels == ["'=HYPERLINK(\"http://x\")"]
    transfers = rows[rows.index(["# transfers"]) + 2:]
    assert transfers[0][:3] == ["0xseed", "0xmid", "10.0"]


def test_export_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine

    from app import models
    from app.main import app

    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True))
    models.init_db()
    models.save_case("case-1", "0xseed", RESULT)
    client = TestClient(app)
    r = client.get("/trace/case-1/graph?format=graphml")
    assert r.status_code == 200 and "graphml" in r.headers["content-disposition"]
    assert client.get("/trace/case-1/graph?format=csv").headers["content-type"].startswith("text/csv")
    assert client.get("/trace/missing/graph").status_code == 404
    assert client.get("/trace/case-1/graph?format=pdf").status_code == 422
