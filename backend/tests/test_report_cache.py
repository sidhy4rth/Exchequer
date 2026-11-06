"""A case's report is rendered once, and PDF renders are bounded.

Before (r1-dos-cost-2), every GET /trace/{id}/report?format=pdf rebuilt, re-signed
and re-typeset the report, with no cache, no limit and no cap on concurrent
renders, for any case id -- public demo ids included -- on a 0.1-CPU instance.
A stored case never changes, so its first render is its report: later downloads
are the same bytes, the text and the PDF's attachment agree, and only a cache
miss spends a PDF render, which is limited per client and site-wide and done
one at a time.
"""
from __future__ import annotations

import io
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine

from app import models, report_cache, signing
from app.main import app
from app.routes import evidence as evidence_routes

from test_report import SEED, full_result


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True))
    models.init_db()
    for n in range(25):
        models.save_case(f"case-{n}", SEED, full_result())
    report_cache.reset()
    yield TestClient(app)
    report_cache.reset()


@pytest.fixture
def renders(monkeypatch):
    calls = []
    real = evidence_routes.render_pdf

    def counting(report, text):
        calls.append(report["case"]["case_id"])
        return real(report, text)

    monkeypatch.setattr(evidence_routes, "render_pdf", counting)
    return calls


def pdf(client, case_id="case-0", **headers):
    return client.get(f"/trace/{case_id}/report?format=pdf", headers=headers)


def test_a_second_pdf_download_does_not_render_again(client, renders):
    first, second = pdf(client), pdf(client)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert renders == ["case-0"]


def test_the_text_and_the_pdf_attachment_are_the_same_report(client):
    text = client.get("/trace/case-0/report?format=text").text
    assert client.get("/trace/case-0/report?format=text").text == text  # same bytes, same generated_at
    (_, [attached]), = PdfReader(io.BytesIO(pdf(client).content)).attachments.items()
    assert attached.decode() == text
    generated = client.get("/trace/case-0/report").json()["generated_at"]
    assert all(client.get("/trace/case-0/report").json()["generated_at"] == generated for _ in range(2))


def test_exports_say_they_may_be_kept(client):
    for fmt in ("text", "pdf"):
        assert client.get(f"/trace/case-0/report?format={fmt}").headers["cache-control"] == "private, max-age=3600"


def test_a_busy_renderer_answers_429(client, renders):
    assert report_cache.render_slot.acquire(blocking=False)
    try:
        r = pdf(client)
    finally:
        report_cache.render_slot.release()
    assert r.status_code == 429 and r.headers["retry-after"] == "5"
    assert renders == []
    assert pdf(client).status_code == 200  # nothing was charged for the refused one


def test_pdf_renders_per_client_are_limited_but_cached_ones_still_answer(client, monkeypatch):
    monkeypatch.setattr(report_cache.pdf_renders, "limit", 3)
    for n in range(3):
        assert pdf(client, f"case-{n}").status_code == 200
    refused = pdf(client, "case-3")
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0
    assert pdf(client, "case-0").status_code == 200  # already rendered: no render spent


def test_pdf_renders_site_wide_are_limited(client, monkeypatch):
    monkeypatch.setattr(report_cache.pdf_renders_total, "limit", 2)
    assert pdf(client, "case-0").status_code == 200
    assert pdf(client, "case-1").status_code == 200
    assert pdf(client, "case-2").status_code == 429


def test_a_new_signing_key_renders_afresh(client, renders):
    pdf(client)
    mine = signing.get_signer()
    signing.reset_for_tests(signing.Signer(Ed25519PrivateKey.generate(), "file"))
    try:
        pdf(client)
    finally:
        signing.reset_for_tests(mine)
    assert renders == ["case-0", "case-0"]


def test_a_different_case_under_a_reused_id_is_not_served_from_the_cache(client, tmp_path, monkeypatch):
    before = client.get("/trace/case-0/report?format=text").text
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'other.db'}", future=True))
    models.init_db()
    models.save_case("case-0", SEED, {**full_result(), "exchange": "Kraken"})
    after = client.get("/trace/case-0/report?format=text").text
    assert after != before and "Kraken" in after


def test_the_cache_is_bounded_in_bytes(monkeypatch):
    cache = report_cache.RenderCache(max_bytes=90, max_item=60)
    cache.put("a", b"x" * 50)
    cache.put("b", b"x" * 50)  # evicts a
    cache.put("big", b"x" * 61)  # never kept
    assert cache.get("a") is None and cache.get("b") == b"x" * 50 and cache.get("big") is None
    assert cache.size <= 90


def test_a_missing_case_is_still_a_404(client):
    assert pdf(client, "nope").status_code == 404
    assert json.loads(client.get("/trace/nope/report?format=text").text)["detail"]


def test_a_graph_export_is_rendered_once(client, monkeypatch):
    from app import graph_export

    calls = []
    real = graph_export.to_graphml
    monkeypatch.setattr(graph_export, "to_graphml", lambda *a: calls.append(a[0]) or real(*a))
    first = client.get("/trace/case-0/graph?format=graphml")
    second = client.get("/trace/case-0/graph?format=graphml")
    assert first.content == second.content and calls == ["case-0"]
    assert second.headers["cache-control"] == "private, max-age=3600"
