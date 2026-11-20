#!/usr/bin/env python3
"""Put one app of the catalog on the marketplace (apps.kode.diy) and submit it for review.

    publish_app.py --app apps/<name> --bin <name>.bin --kappdata-dir DIR [--as HANDLE] [--api URL] [--dry-run]

The workflow runs it on main, for each app a push adds or moves, with the
`.bin` the rules passed on the same commit, as the publisher `kode`: every
listing of the catalog belongs to Kode. The token is KODE_MARKETPLACE_TOKEN
in the environment: the agent token (`apps:write`) of a marketplace admin,
which acts as the publisher through `?as=<handle>` on every call and signs
each upload with the admin's own name.

The slug is the app's identity there (kcheck.listing.slug), so a new version
is a republish of the same app: same id, page and download link. Steps:

1. The publisher's own listing of the slug, from `GET /apps/mine`: a version
   there already at or above this one ends the run, published (so a run
   repeated, or one that lost a race, changes nothing).
2. The icon goes up as the cover (`POST /apps/upload-cover`): a submission
   without one is refused, and so is a cover with transparency, so an icon
   with an alpha channel goes laid on the app's colour (kcheck.cover).
3. Each screenshot of appdata/screenshots/ goes up (`POST
   /apps/upload-screenshot`), in the order of their names; the page shows
   them between the install button and the text.
4. The upload (`POST /apps/upload`) with `status=published`, which submits
   it for review. The text is appdata/store.md (rule A7) when the app has
   one, app.json's one line when not, and the screenshots go as their urls. A submission still pending is withdrawn first: the
   catalog's main is what the marketplace is meant to show.

Exits 0 when the app is submitted or already there, 1 otherwise. The contract
is https://api.kode.diy/agents/upload.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kcheck import cover, listing  # noqa: E402
from kcheck.rules_a import VERSION_RE, version_tuple  # noqa: E402

API = "https://api.kode.diy"
PAGE = "https://apps.kode.diy/app/"
TOKEN_ENV = "KODE_MARKETPLACE_TOKEN"
USER_AGENT = "kode-apps-publish"
TIMEOUT_S = 120  # an upload of a few MB, with room for a slow link
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def multipart(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    """A multipart/form-data body of text fields and files, and its Content-Type."""
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
                     + value.encode() + b"\r\n")
    for key, path in files.items():
        kind = IMAGE_TYPES.get(path.suffix.lower(), "application/octet-stream")
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{path.name}"\r\n'
                f"Content-Type: {kind}\r\n\r\n")
        parts.append(head.encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class Api:
    def __init__(self, base: str, token: str, acting: str | None = None):
        self.base = base.rstrip("/")
        self.token = token
        self.acting = acting

    def url(self, path: str) -> str:
        """The full URL of path, acting as the publisher when there is one."""
        if self.acting:
            return f"{self.base}{path}?{urllib.parse.urlencode({'as': self.acting})}"
        return self.base + path

    def call(self, method: str, path: str, body: bytes | None = None,
             content_type: str | None = None) -> tuple[int, dict]:
        """(HTTP status, JSON body or {}) of one request; an HTTP error is a status, not a raise."""
        req = urllib.request.Request(self.url(path), data=body, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("User-Agent", USER_AGENT)
        if content_type:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                status, text = r.status, r.read()
        except urllib.error.HTTPError as exc:
            status, text = exc.code, exc.read()
        try:
            data = json.loads(text) if text else {}
        except ValueError:
            data = {"error": text[:200].decode(errors="replace")}
        return status, data if isinstance(data, dict) else {"items": data}


def mine(api: Api, slug: str) -> dict | None:
    """The account's own row for slug, drafts included, or None when it has none."""
    status, body = api.call("GET", "/apps/mine")
    if status != 200:
        raise RuntimeError(f"GET /apps/mine answered {status}: {body.get('error', body)}")
    rows = body.get("apps", body.get("items", []))
    return next((row for row in rows if row.get("slug") == slug), None)


def is_at_or_above(stored: str | None, ours: str) -> bool:
    if not stored or not VERSION_RE.fullmatch(stored):
        return False
    return version_tuple(stored) >= version_tuple(ours)


def upload_screenshots(api: Api, info: dict) -> list[str] | None:
    """The urls of the app's screenshots once stored, in order; None when one is refused."""
    urls = []
    for shot in info.get("screenshots", []):
        body, kind = multipart({}, {"file": shot})
        status, got = api.call("POST", "/apps/upload-screenshot", body, kind)
        if status not in (200, 201) or not got.get("url"):
            print(f"{info['slug']}: the screenshot {shot.name} answered {status}: {got.get('error', got)}",
                  file=sys.stderr)
            return None
        urls.append(got["url"])
    return urls


def upload(api: Api, info: dict, cover_url: str, binary: Path, shots: list[str]) -> tuple[int, dict]:
    fields = {
        "slug": info["slug"],
        "name": info["name"],
        "version": info["version"],
        "category": info["category"],
        "description": info["description"],
        "githubUrl": info["githubUrl"],
        "coverImageUrl": cover_url,
        "status": "published",
    }
    if shots:
        fields["screenshots"] = json.dumps(shots)
    body, kind = multipart(fields, {"file": binary})
    return api.call("POST", "/apps/upload", body, kind)


def publish(api: Api, info: dict, binary: Path) -> int:
    row = mine(api, info["slug"])
    if row is not None and is_at_or_above(row.get("version"), info["version"]):
        print(f"{info['slug']}: the marketplace already has {row.get('version')} "
              f"({row.get('reviewState')}), nothing to do: {PAGE}{row.get('id')}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        face = Path(tmp) / info["icon"].name
        face.write_bytes(cover.opaque(info["icon"].read_bytes(), info["color"]))
        body, kind = multipart({}, {"file": face})
    status, got = api.call("POST", "/apps/upload-cover", body, kind)
    cover_url = got.get("url")
    if status not in (200, 201) or not cover_url:
        print(f"{info['slug']}: the cover upload answered {status}: {got.get('error', got)}", file=sys.stderr)
        return 1

    shots = upload_screenshots(api, info)
    if shots is None:
        return 1

    status, got = upload(api, info, cover_url, binary, shots)
    if status == 409 and got.get("error") == "in_review" and row is not None:
        print(f"{info['slug']}: withdrawing the submission still pending, so this version replaces it")
        withdrawn, why = api.call("DELETE", f"/apps/{row['id']}/submit")
        if withdrawn >= 300:
            print(f"{info['slug']}: the withdrawal answered {withdrawn}: {why.get('error', why)}", file=sys.stderr)
            return 1
        status, got = upload(api, info, cover_url, binary, shots)
    if status not in (200, 201):
        print(f"{info['slug']}: the upload answered {status}: {got.get('error', got)}", file=sys.stderr)
        return 1
    if got.get("submitError"):
        print(f"{info['slug']}: uploaded as a draft but not submitted: {got['submitError']}", file=sys.stderr)
        return 1
    state = (got.get("submission") or {}).get("status", "unknown")
    print(f"{info['slug']} {info['version']}: submitted for review ({state}): {PAGE}{got.get('id')}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", type=Path, required=True)
    ap.add_argument("--bin", type=Path, required=True)
    ap.add_argument("--kappdata-dir", type=Path, required=True)
    ap.add_argument("--as", dest="acting", help="the publisher handle to act as, e.g. kode")
    ap.add_argument("--api", default=API)
    ap.add_argument("--dry-run", action="store_true", help="print the listing, send nothing")
    a = ap.parse_args(argv)
    if not a.bin.is_file():
        print(f"no such file: {a.bin}", file=sys.stderr)
        return 1
    try:
        info = listing.listing(a.app, a.kappdata_dir)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if a.dry_run:
        shown = dict(info, icon=str(info["icon"]), screenshots=[str(p) for p in info["screenshots"]],
                     bin=str(a.bin), size=a.bin.stat().st_size)
        print(json.dumps(shown, indent=2))
        return 0
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        print(f"{TOKEN_ENV} is not set", file=sys.stderr)
        return 1
    try:
        return publish(Api(a.api, token, a.acting), info, a.bin)
    except (RuntimeError, OSError) as exc:
        print(f"{info['slug']}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
