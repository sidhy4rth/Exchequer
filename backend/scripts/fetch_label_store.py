"""Install the risk-label store into the image at build time, from a PRIVATE release.

The store (app/label_store.py) is millions of rows of hunt output: far past
GitHub's file limit, and not something to publish. So it is kept as a gzip
release asset in a private repository and fetched while the image is built,
with a read-only token that arrives as a build secret (a Render "Secret File"
named label_store_token), so the token never lands in a layer or in git.

    LABEL_STORE_REPO     owner/name of the private repository
    LABEL_STORE_TAG      release tag holding label_store.db.gz (or its parts, below)
    LABEL_STORE_SHA256   sha256 of label_store.db.gz; the build fails on a mismatch
    token                /run/secrets/label_store_token (or LABEL_STORE_TOKEN_FILE)
    LABEL_STORE_REQUIRED 1 (the image's default) makes a missing store fail the build

Required and not configured, or no token: exits 1, so a deploy whose build
secret went missing fails and the running version stays up, rather than
shipping without its labels unnoticed. Not required (CI's image job, a fork, a
local build): prints why and exits 0, and the site screens against the label
files only. Configured but the download or checksum fails, or the installed
file does not open as a label store with rows in it: exits 1 either way.

GitHub refuses a release asset of 2 GiB or more, so a larger gzip is uploaded
in parts: label_store.db.gz.part-aa, .part-ab, ... as written by
`split -b <size> label_store.db.gz label_store.db.gz.part-`. A release with no
label_store.db.gz has its parts downloaded in name order and joined back into
that one file; a release that has it is read as before, whatever else it
holds. LABEL_STORE_SHA256 is always the sha256 of the whole gzip, never of a part.

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
PART_PREFIX = ASSET + ".part-"  # split's output: .part-aa, .part-ab, ...
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
    try:
        with gzip.open(gz_path, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        tmp.replace(out)
    except BaseException:
        # Private hunt data: never leave a half-written copy beside the store.
        tmp.unlink(missing_ok=True)
        raise


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


def _part_name(index: int) -> str:
    """The name `split` gives its `index`-th piece: aa, ab, ... az, ba, ... zz."""
    return PART_PREFIX + chr(97 + index // 26) + chr(97 + index % 26)


def _assets(release: dict, repo: str, tag: str) -> list[dict]:
    """The release assets that make up the gzip, in the order to join them.

    The whole file as one asset wins. Otherwise its parts, which must be the
    run split writes, from aa with no gap: a part that was never uploaded
    would otherwise only show up as a checksum that does not match.
    """
    assets = [a for a in release.get("assets", []) if isinstance(a, dict)]
    chosen = [a for a in assets if a.get("name") == ASSET][:1]
    if not chosen:
        chosen = sorted((a for a in assets if str(a.get("name", "")).startswith(PART_PREFIX)),
                        key=lambda a: a["name"])
        if not chosen:
            raise LookupError(f"release {tag} has no {ASSET} and no {PART_PREFIX}aa, -ab, ... parts")
        if len(chosen) > 26 * 26:
            raise LookupError(f"release {tag} has more {PART_PREFIX}* assets than split's two letters name")
        for index, part in enumerate(chosen):
            if part["name"] != _part_name(index):
                raise LookupError(f"release {tag} has {part['name']} where {_part_name(index)} should be: "
                                  "the parts must run aa, ab, ... with none missing")
    for asset in chosen:
        if not str(asset.get("url", "")).startswith(f"{API}/repos/{repo}/releases/assets/"):
            raise LookupError(f"release {tag} lists {asset['name']} at an unexpected URL")
    return chosen


def main() -> int:
    repo = os.getenv("LABEL_STORE_REPO", "").strip()
    tag = os.getenv("LABEL_STORE_TAG", "").strip()
    sha = os.getenv("LABEL_STORE_SHA256", "").strip()
    token_file = Path(os.getenv("LABEL_STORE_TOKEN_FILE", "/run/secrets/label_store_token"))
    token = token_file.read_text().strip() if token_file.is_file() else ""
    required = os.getenv("LABEL_STORE_REQUIRED", "").strip().lower() in ("1", "true", "yes", "on")
    print(f"label store: required={int(required)}")
    missing = ("not configured" if not (repo and tag and sha)
               else f"no token at {token_file}" if not token else None)
    if missing and required:
        print(f"label store: {missing}, and this build requires the store "
              "(LABEL_STORE_REQUIRED=0 builds without it)", file=sys.stderr)
        return 1
    if missing:
        print(f"label store: {missing}; screening uses the label files only")
        return 0
    try:
        with _get(f"{API}/repos/{repo}/releases/tags/{tag}", token, "application/vnd.github+json") as r:
            release = json.load(r)
        assets = _assets(release, repo, tag)
        with tempfile.TemporaryDirectory() as tmpdir:
            gz = Path(tmpdir) / ASSET
            # Parts are appended to the one file as they arrive, so the small
            # build machine never holds the gzip twice.
            with open(gz, "wb") as fh:
                for asset in assets:
                    with _get(asset["url"], token, "application/octet-stream") as r:
                        shutil.copyfileobj(r, fh, 1 << 20)
            install(gz, sha, DEFAULT_OUT)
        rows = _rows(DEFAULT_OUT)
    except Exception as exc:  # noqa: BLE001 -- any failure must fail the build loudly
        # Never echo the token; the exception text carries only URLs and status.
        print(f"label store: FAILED ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    print(f"label store: installed {repo}@{tag} -> {DEFAULT_OUT} "
          f"({DEFAULT_OUT.stat().st_size / 1e6:.0f} MB, {rows:,} rows)")
    return 0


def _rows(path: Path) -> int:
    """Open the installed file the way the app will, and count its rows.

    A file that passes its checksum can still be the wrong thing (an older
    schema, an empty build); the app would only log that and screen without
    it, so the build fails here instead. An unusable file is removed.
    """
    from app.label_store import LabelStore

    try:
        rows = len(LabelStore(path))
        if rows == 0:
            raise ValueError(f"{path.name} holds no labels")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
