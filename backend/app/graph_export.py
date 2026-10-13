"""A stored case's transfer graph in formats other tools open.

GraphML loads straight into Gephi, yEd, Cytoscape and Maltego (via its
GraphML import), so an analyst can lay the trace out beside their own data.
CSV is the same graph as two flat tables for a spreadsheet: one row per
address, one per transfer edge, written into a single file with a section
header each so it travels as one attachment.

Read from the stored case only -- exactly the graph the investigator saw,
never a re-trace.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape, quoteattr

NODE_FIELDS = [
    ("address", "string"), ("depth", "int"), ("role", "string"), ("label", "string"),
    ("exchange", "string"), ("inferred_exchange", "string"), ("risk_category", "string"),
    ("risk_label", "string"), ("total_in", "double"), ("total_out", "double"),
    ("activity_count", "int"), ("flags", "string"),
]
EDGE_FIELDS = [
    ("value", "double"), ("asset", "string"), ("tx_count", "int"), ("first_seen", "string"),
    ("last_seen", "string"), ("on_principal_path", "boolean"), ("flags", "string"),
]


def _iso(ts: Any) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return ""


def _role(node: dict[str, Any]) -> str:
    if node.get("is_seed"):
        return "reported"
    if node.get("risk_category"):
        return node["risk_category"]
    if node.get("exchange"):
        return "exchange"
    if node.get("inferred_exchange"):
        return "probable deposit"
    if node.get("is_router"):
        return "dex router"
    if node.get("is_service_contract"):
        return "service contract"
    return "wallet"


def _rows(result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    graph = result.get("graph") or {}
    asset = result.get("asset") or result.get("native_symbol") or ""
    path = [step.get("address") for step in result.get("trace_path") or []]
    on_path = {(a, b) for a, b in zip(path, path[1:], strict=False)}  # consecutive pairs
    nodes = [{
        "address": n.get("id"),
        "depth": n.get("depth"),
        "role": _role(n),
        "label": n.get("label") or "",
        "exchange": n.get("exchange") or "",
        "inferred_exchange": n.get("inferred_exchange") or "",
        "risk_category": n.get("risk_category") or "",
        "risk_label": n.get("risk_label") or "",
        "total_in": n.get("total_in_native") or 0,
        "total_out": n.get("total_out_native") or 0,
        "activity_count": n.get("activity_count") or 0,
        "flags": ";".join(n.get("flags") or []),
    } for n in graph.get("nodes", [])]
    edges = [{
        "source": e.get("source"),
        "target": e.get("target"),
        "value": e.get("value_native") or 0,
        "asset": asset,
        "tx_count": e.get("tx_count") or 0,
        "first_seen": _iso(e.get("first_seen")),
        "last_seen": _iso(e.get("last_seen")),
        "on_principal_path": (e.get("source"), e.get("target")) in on_path,
        "flags": ";".join(e.get("flags") or []),
    } for e in graph.get("edges", [])]
    return nodes, edges


def to_csv(case_id: str, result: dict[str, Any]) -> str:
    nodes, edges = _rows(result)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([f"# Exchequer case {case_id}", f"reported {result.get('address', '')}",
                     f"chain {result.get('chain', '')}", f"asset {result.get('asset', '')}"])
    writer.writerow([])
    writer.writerow(["# addresses"])
    writer.writerow([name for name, _ in NODE_FIELDS])
    for row in nodes:
        writer.writerow([_cell(row[name]) for name, _ in NODE_FIELDS])
    writer.writerow([])
    writer.writerow(["# transfers"])
    writer.writerow(["source", "target"] + [name for name, _ in EDGE_FIELDS])
    for row in edges:
        writer.writerow([row["source"], row["target"]] + [_cell(row[name]) for name, _ in EDGE_FIELDS])
    return out.getvalue()


def _cell(value: Any) -> Any:
    # A label beginning with = + - @ would run as a formula when the CSV is
    # opened in a spreadsheet; label files come from third parties.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def to_graphml(case_id: str, result: dict[str, Any]) -> str:
    nodes, edges = _rows(result)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
    ]
    for name, kind in NODE_FIELDS:
        lines.append(f'  <key id="n_{name}" for="node" attr.name="{name}" attr.type="{kind}"/>')
    for name, kind in EDGE_FIELDS:
        lines.append(f'  <key id="e_{name}" for="edge" attr.name="{name}" attr.type="{kind}"/>')
    lines.append(f'  <graph id={quoteattr("exchequer-" + case_id)} edgedefault="directed">')
    for row in nodes:
        lines.append(f'    <node id={quoteattr(str(row["address"]))}>')
        lines += [f'      <data key="n_{name}">{escape(_text(row[name]))}</data>'
                  for name, _ in NODE_FIELDS]
        lines.append("    </node>")
    for i, row in enumerate(edges):
        lines.append(f'    <edge id="e{i}" source={quoteattr(str(row["source"]))} '
                     f'target={quoteattr(str(row["target"]))}>')
        lines += [f'      <data key="e_{name}">{escape(_text(row[name]))}</data>'
                  for name, _ in EDGE_FIELDS]
        lines.append("    </edge>")
    lines += ["  </graph>", "</graphml>", ""]
    return "\n".join(lines)


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)
