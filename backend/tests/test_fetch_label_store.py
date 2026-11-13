"""The build-time fetch of the private label store.

It must never break a build that has no token (CI, a fork, a local docker
build), must refuse a file whose checksum does not match, and must leave no
half-written store behind.
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import sqlite3
import urllib.error

import pytest

from scripts import fetch_label_store as fetch


def test_unconfigured_or_tokenless_builds_still_succeed(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("LABEL_STORE_REQUIRED", raising=False)
    for key in ("LABEL_STORE_REPO", "LABEL_STORE_TAG", "LABEL_STORE_SHA256"):
        monkeypatch.delenv(key, raising=False)
    assert fetch.main() == 0
    assert "not configured" in capsys.readouterr().out

    monkeypatch.setenv("LABEL_STORE_REPO", "owner/private")
    monkeypatch.setenv("LABEL_STORE_TAG", "t")
    monkeypatch.setenv("LABEL_STORE_SHA256", "0" * 64)
    monkeypatch.setenv("LABEL_STORE_TOKEN_FILE", str(tmp_path / "absent"))
    assert fetch.main() == 0
    assert "no token" in capsys.readouterr().out


def test_install_verifies_the_checksum_and_writes_atomically(tmp_path):
    payload = b"SQLite format 3\x00" + b"x" * 1000
    gz = tmp_path / "label_store.db.gz"
    gz.write_bytes(gzip.compress(payload))
    out = tmp_path / "data" / "label_store.db"

    with pytest.raises(ValueError, match="checksum mismatch"):
        fetch.install(gz, "0" * 64, out)
    assert not out.exists() and not out.with_suffix(".partial").exists()

    fetch.install(gz, hashlib.sha256(gz.read_bytes()).hexdigest(), out)
    assert out.read_bytes() == payload


# -- the token goes to the GitHub API and nowhere else (r1-scripts-11) ----------
ASSET_URL = "https://api.github.com/repos/o/r/releases/assets/1"


def configure(monkeypatch, tmp_path, token="TOKEN-SECRET"):
    monkeypatch.setenv("LABEL_STORE_REPO", "o/r")
    monkeypatch.setenv("LABEL_STORE_TAG", "t")
    monkeypatch.setenv("LABEL_STORE_SHA256", "0" * 64)
    secret = tmp_path / "token"
    secret.write_text(token)
    monkeypatch.setenv("LABEL_STORE_TOKEN_FILE", str(secret))
    monkeypatch.setattr(fetch, "DEFAULT_OUT", tmp_path / "data" / "label_store.db")


def test_the_token_does_not_follow_a_redirect():
    req = fetch._request(ASSET_URL, "TOKEN-SECRET", "application/octet-stream")
    # Sent to the API itself, but as a header urllib never copies onto a redirect.
    assert req.unredirected_hdrs["Authorization"] == "Bearer TOKEN-SECRET"
    assert "TOKEN-SECRET" not in str(req.headers)
    new = fetch._HttpsOnlyRedirect().redirect_request(
        req, io.BytesIO(), 302, "Found", {}, "https://objects.githubusercontent.com/x?sig=1")
    assert not new.has_header("Authorization")
    assert all("TOKEN-SECRET" not in value for _, value in new.header_items())


def test_a_plain_http_redirect_is_refused():
    req = fetch._request(ASSET_URL, "TOKEN-SECRET", "application/octet-stream")
    with pytest.raises(urllib.error.HTTPError):
        fetch._HttpsOnlyRedirect().redirect_request(
            req, io.BytesIO(), 302, "Found", {}, "http://objects.githubusercontent.com/x")


def test_the_token_is_never_sent_off_the_api():
    with pytest.raises(ValueError, match="evil.example"):
        fetch._request("https://evil.example/x", "TOKEN-SECRET", "application/octet-stream")


def test_an_asset_url_off_the_api_is_refused(monkeypatch, tmp_path, capsys):
    configure(monkeypatch, tmp_path)
    called = []

    def fake_get(url, token, accept):
        called.append(url)
        release = {"assets": [{"name": fetch.ASSET, "url": "https://evil.example/x"}]}
        return contextlib.nullcontext(io.BytesIO(json.dumps(release).encode()))

    monkeypatch.setattr(fetch, "_get", fake_get)
    assert fetch.main() == 1
    assert called == ["https://api.github.com/repos/o/r/releases/tags/t"]
    assert "TOKEN-SECRET" not in capsys.readouterr().err


# -- a deploy that needs the store fails without it (r1-scripts-12) -------------
def test_a_required_store_fails_without_a_token(monkeypatch, tmp_path, capsys):
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv("LABEL_STORE_TOKEN_FILE", str(tmp_path / "absent"))
    monkeypatch.setenv("LABEL_STORE_REQUIRED", "1")
    assert fetch.main() == 1
    captured = capsys.readouterr()
    assert "required=1" in captured.out and "no token" in captured.err


def test_a_required_store_fails_when_not_configured(monkeypatch, capsys):
    for key in ("LABEL_STORE_REPO", "LABEL_STORE_TAG", "LABEL_STORE_SHA256"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LABEL_STORE_REQUIRED", "1")
    assert fetch.main() == 1
    assert "not configured" in capsys.readouterr().err


def fake_release(monkeypatch, gz_bytes: bytes):
    def fake_get(url, token, accept):
        if url.endswith("/releases/tags/t"):
            release = {"assets": [{"name": fetch.ASSET, "url": ASSET_URL}]}
            return contextlib.nullcontext(io.BytesIO(json.dumps(release).encode()))
        assert url == ASSET_URL
        return contextlib.nullcontext(io.BytesIO(gz_bytes))

    monkeypatch.setattr(fetch, "_get", fake_get)


def test_an_installed_store_that_does_not_open_fails_the_build(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    junk = tmp_path / "junk.db"
    db = sqlite3.connect(junk)
    db.execute("CREATE TABLE stray (x)")
    db.commit()
    db.close()
    gz = gzip.compress(junk.read_bytes())
    monkeypatch.setenv("LABEL_STORE_SHA256", hashlib.sha256(gz).hexdigest())
    fake_release(monkeypatch, gz)
    assert fetch.main() == 1


def test_an_installed_store_reports_its_rows(monkeypatch, tmp_path, capsys):
    from scripts.build_label_store import build

    configure(monkeypatch, tmp_path)
    src = tmp_path / "flagged.csv"
    src.write_text("address,chain,category,entity_or_incident,sources,source_refs,date\n"
                   f"0x{'5c' * 20},ethereum,phishing/scam,Drainer,Threat-intel report: Check Point,,\n")
    built = tmp_path / "built.db"
    build(src, built)
    gz = gzip.compress(built.read_bytes())
    monkeypatch.setenv("LABEL_STORE_SHA256", hashlib.sha256(gz).hexdigest())
    monkeypatch.setenv("LABEL_STORE_REQUIRED", "1")
    fake_release(monkeypatch, gz)
    assert fetch.main() == 0
    assert "1 rows" in capsys.readouterr().out


def test_a_broken_gzip_leaves_no_partial_file(tmp_path):
    """r1-scripts-13: the half-written private store must not linger in data/."""
    whole = gzip.compress(b"SQLite format 3\x00" + bytes(range(256)) * 400)
    gz = tmp_path / "label_store.db.gz"
    gz.write_bytes(whole[: len(whole) // 2])  # truncated, but its checksum is the one asked for
    out = tmp_path / "data" / "label_store.db"
    with pytest.raises((EOFError, gzip.BadGzipFile)):
        fetch.install(gz, hashlib.sha256(gz.read_bytes()).hexdigest(), out)
    assert not out.exists() and not out.with_suffix(".partial").exists()


# -- a store past GitHub's 2 GiB asset limit arrives in parts --------------------
def part_url(number: int) -> str:
    return f"https://api.github.com/repos/o/r/releases/assets/{number}"


def fake_parts_release(monkeypatch, parts: dict[str, bytes], order: list[str] | None = None) -> list[str]:
    """A release whose assets are `parts` (name -> bytes), listed in `order`.

    Returns the list the asset downloads are recorded in, as asset names.
    """
    names = order or list(parts)
    urls = {name: part_url(10 + i) for i, name in enumerate(parts)}
    by_url = {url: name for name, url in urls.items()}
    fetched: list[str] = []

    def fake_get(url, token, accept):
        if url.endswith("/releases/tags/t"):
            release = {"assets": [{"name": name, "url": urls[name]} for name in names]}
            return contextlib.nullcontext(io.BytesIO(json.dumps(release).encode()))
        fetched.append(by_url[url])
        return contextlib.nullcontext(io.BytesIO(parts[by_url[url]]))

    monkeypatch.setattr(fetch, "_get", fake_get)
    return fetched


def built_store_gz(tmp_path) -> bytes:
    from scripts.build_label_store import build

    src = tmp_path / "flagged.csv"
    src.write_text("address,chain,category,entity_or_incident,sources,source_refs,date\n"
                   f"0x{'5c' * 20},ethereum,phishing/scam,Drainer,Threat-intel report: Check Point,,\n")
    built = tmp_path / "built.db"
    build(src, built)
    return gzip.compress(built.read_bytes())


def split3(gz: bytes) -> dict[str, bytes]:
    third = len(gz) // 3
    return {fetch.ASSET + ".part-aa": gz[:third],
            fetch.ASSET + ".part-ab": gz[third:2 * third],
            fetch.ASSET + ".part-ac": gz[2 * third:]}


def test_part_names_follow_split():
    names = [fetch._part_name(i).removeprefix(fetch.PART_PREFIX) for i in (0, 1, 25, 26, 27, 675)]
    assert names == ["aa", "ab", "az", "ba", "bb", "zz"]


def test_a_store_in_parts_installs_the_same_database(monkeypatch, tmp_path, capsys):
    configure(monkeypatch, tmp_path)
    gz = built_store_gz(tmp_path)
    monkeypatch.setenv("LABEL_STORE_SHA256", hashlib.sha256(gz).hexdigest())
    monkeypatch.setenv("LABEL_STORE_REQUIRED", "1")

    fake_release(monkeypatch, gz)
    assert fetch.main() == 0
    single = fetch.DEFAULT_OUT.read_bytes()
    fetch.DEFAULT_OUT.unlink()
    capsys.readouterr()

    fetched = fake_parts_release(monkeypatch, split3(gz))
    assert fetch.main() == 0
    assert "1 rows" in capsys.readouterr().out
    assert fetched == [fetch.ASSET + suffix for suffix in (".part-aa", ".part-ab", ".part-ac")]
    assert fetch.DEFAULT_OUT.read_bytes() == single == gzip.decompress(gz)


def test_parts_listed_out_of_order_are_joined_in_name_order(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    gz = built_store_gz(tmp_path)
    monkeypatch.setenv("LABEL_STORE_SHA256", hashlib.sha256(gz).hexdigest())
    parts = split3(gz)
    shuffled = [fetch.ASSET + ".part-ac", "notes.txt", fetch.ASSET + ".part-aa", fetch.ASSET + ".part-ab"]
    fetched = fake_parts_release(monkeypatch, {**parts, "notes.txt": b"unrelated"}, order=shuffled)
    assert fetch.main() == 0
    assert fetched == sorted(parts)
    assert fetch.DEFAULT_OUT.read_bytes() == gzip.decompress(gz)


def test_the_single_asset_wins_over_parts(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    gz = built_store_gz(tmp_path)
    monkeypatch.setenv("LABEL_STORE_SHA256", hashlib.sha256(gz).hexdigest())
    # The parts here are junk and gapped: with the whole file present they are not looked at.
    fetched = fake_parts_release(monkeypatch, {fetch.ASSET + ".part-ab": b"junk", fetch.ASSET: gz})
    assert fetch.main() == 0
    assert fetched == [fetch.ASSET]


def test_a_missing_middle_part_fails_and_installs_nothing(monkeypatch, tmp_path, capsys):
    configure(monkeypatch, tmp_path)
    gz = built_store_gz(tmp_path)
    monkeypatch.setenv("LABEL_STORE_SHA256", hashlib.sha256(gz).hexdigest())
    parts = split3(gz)
    del parts[fetch.ASSET + ".part-ab"]
    fetched = fake_parts_release(monkeypatch, parts)
    assert fetch.main() == 1
    err = capsys.readouterr().err
    assert "part-ab" in err and "TOKEN-SECRET" not in err
    assert fetched == []  # refused before any download
    assert not fetch.DEFAULT_OUT.exists() and not fetch.DEFAULT_OUT.with_suffix(".partial").exists()


def test_parts_that_do_not_start_at_aa_fail(monkeypatch, tmp_path, capsys):
    configure(monkeypatch, tmp_path)
    parts = split3(built_store_gz(tmp_path))
    del parts[fetch.ASSET + ".part-aa"]
    fake_parts_release(monkeypatch, parts)
    assert fetch.main() == 1
    assert "part-aa" in capsys.readouterr().err
    assert not fetch.DEFAULT_OUT.exists()


def test_a_wrong_checksum_over_the_joined_parts_leaves_nothing(monkeypatch, tmp_path, capsys):
    configure(monkeypatch, tmp_path)  # LABEL_STORE_SHA256 is all zeros
    fetched = fake_parts_release(monkeypatch, split3(built_store_gz(tmp_path)))
    assert fetch.main() == 1
    assert "checksum mismatch" in capsys.readouterr().err
    assert len(fetched) == 3
    assert not fetch.DEFAULT_OUT.exists() and not fetch.DEFAULT_OUT.with_suffix(".partial").exists()


def test_a_release_with_neither_the_file_nor_parts_fails(monkeypatch, tmp_path, capsys):
    configure(monkeypatch, tmp_path)
    fetched = fake_parts_release(monkeypatch, {"notes.txt": b"unrelated"})
    assert fetch.main() == 1
    err = capsys.readouterr().err
    assert f"has no {fetch.ASSET}" in err and "part" in err
    assert fetched == [] and not fetch.DEFAULT_OUT.exists()


def test_a_part_url_off_the_api_is_refused(monkeypatch, tmp_path, capsys):
    configure(monkeypatch, tmp_path)
    called = []

    def fake_get(url, token, accept):
        called.append(url)
        release = {"assets": [{"name": fetch.ASSET + ".part-aa", "url": part_url(1)},
                              {"name": fetch.ASSET + ".part-ab", "url": "https://evil.example/x"}]}
        return contextlib.nullcontext(io.BytesIO(json.dumps(release).encode()))

    monkeypatch.setattr(fetch, "_get", fake_get)
    assert fetch.main() == 1
    assert called == ["https://api.github.com/repos/o/r/releases/tags/t"]  # no part was fetched
    assert "TOKEN-SECRET" not in capsys.readouterr().err
