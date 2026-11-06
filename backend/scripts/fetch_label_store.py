"""Install the risk-label store into the image at build time, from a PRIVATE release.

The store (app/label_store.py) is millions of rows of hunt output: far past
GitHub's file limit, and not something to publish. So it is kept as a gzip
release asset in a private repository and fetched while the image is built,
with a read-only token that arrives as a build secret (a Render "Secret File"
named label_store_token), so the token never lands in a layer or in git.

    LABEL_STORE_REPO     owner/name of the private repository
    LABEL_STORE_TAG      release tag holding label_store.db.gz
    LABEL_STORE_SHA256   sha256 of label_store.db.gz; the build fails on a mismatch
    token                /run/secrets/label_store_token (or LABEL_STORE_TOKEN_FILE)

Nothing configured, or no token: prints why and exits 0, and the site runs
exactly as before, screening against the label files only. Configured but the
download or checksum fails: exits 1, so the deploy fails and the running
version stays up rather than shipping without its labels unnoticed.

    python -m scripts.fetch_label_store
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ASSET = "label_store.db.gz"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "label_store.db"
API = "https://api.github.com"


def install(gz_path: Path, sha256: str, out: Path) -> None:
    """Verify `gz_path` against `sha256`, then decompress it to `out` atomically."""
    digest = hashlib.sha256()
    with open(gz_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != sha256.lower():
        raise ValueError(f"checksum mismatch: got {digest.hexdigest()}, expected {sha256}")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".partial")
    with gzip.open(gz_path, "rb") as src, open(tmp, "wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
    tmp.replace(out)


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to https: the asset download is a 302 to a pre-signed CDN URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise urllib.error.HTTPError(newurl, code, "refusing a non-https redirect", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsOnlyRedirect)


def _request(url: str, token: str, accept: str) -> urllib.request.Request:
    """A request carrying the token to the GitHub API, and to no other host.

    An ordinary header is copied onto every redirect, whatever its host; the
    CDN the asset redirects to is pre-signed and needs no token, so the token
    is an unredirected header and never leaves the API.
    """
    if not url.startswith(API + "/"):
        raise ValueError(f"refusing to send the token to {urllib.parse.urlsplit(url).netloc}")
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "exchequer-build"})
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    return req


def _get(url: str, token: str, accept: str) -> urllib.request.addinfourl:
    return _OPENER.open(_request(url, token, accept), timeout=120)


def main() -> int:
    repo = os.getenv("LABEL_STORE_REPO", "").strip()
    tag = os.getenv("LABEL_STORE_TAG", "").strip()
    sha = os.getenv("LABEL_STORE_SHA256", "").strip()
    token_file = Path(os.getenv("LABEL_STORE_TOKEN_FILE", "/run/secrets/label_store_token"))
    token = token_file.read_text().strip() if token_file.is_file() else ""
    if not (repo and tag and sha):
        print("label store: not configured; screening uses the label files only")
        return 0
    if not token:
        print(f"label store: no token at {token_file}; screening uses the label files only")
        return 0
    try:
        with _get(f"{API}/repos/{repo}/releases/tags/{tag}", token, "application/vnd.github+json") as r:
            release = json.load(r)
        asset = next((a for a in release.get("assets", []) if a.get("name") == ASSET), None)
        if asset is None:
            raise LookupError(f"release {tag} has no {ASSET}")
        if not str(asset.get("url", "")).startswith(f"{API}/repos/{repo}/releases/assets/"):
            raise LookupError(f"release {tag} lists {ASSET} at an unexpected URL")
        with tempfile.TemporaryDirectory() as tmpdir:
            gz = Path(tmpdir) / ASSET
            with _get(asset["url"], token, "application/octet-stream") as r, open(gz, "wb") as fh:
                shutil.copyfileobj(r, fh, 1 << 20)
            install(gz, sha, DEFAULT_OUT)
    except Exception as exc:  # noqa: BLE001 -- any failure must fail the build loudly
        # Never echo the token; the exception text carries only URLs and status.
        print(f"label store: FAILED ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    print(f"label store: installed {repo}@{tag} -> {DEFAULT_OUT} ({DEFAULT_OUT.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
