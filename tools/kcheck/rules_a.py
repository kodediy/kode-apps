"""Rules of block A of RULES.md: identity, metadata, licence and version.

A1 and the catalog-wide half of A2 live in catalog.py, since they read the
catalog and not the app.
"""
from __future__ import annotations

import importlib.util
import json
import re

from kcheck import catalog, source
from kcheck.core import Finding, rule

DISPLAY_MAX = 31
CATEGORIES_MAX = 4
APP_JSON_KEYS = ("kode", "color", "description", "icon")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
# A7: the text of the app's page on the marketplace. app.json's description is
# the line kodeOS shows under the icon (52 characters); this is the page.
STORE_TEXT = "appdata/store.md"
STORE_TEXT_MIN = 200
STORE_TEXT_MAX = 2000
# What the marketplace strips to text (https://api.kode.diy/agents/upload.md):
# a heading, a link or an image, and raw HTML.
STORE_TEXT_STRIPPED = (
    (re.compile(r"^\s{0,3}#{1,6}\s", re.M), "a heading"),
    (re.compile(r"!?\[[^\]]*\]\([^)]*\)"), "a link or an image"),
    (re.compile(r"</?[A-Za-z][^>]*>"), "raw HTML"),
)


@rule("A2", "reject")
def a2_project_name(ctx):
    project = source.cmake_project(ctx.app)
    if project is None:
        yield Finding("A2", "reject", "CMakeLists.txt", 0, "no project(<name>) line")
        return
    if project != ctx.name:
        yield Finding("A2", "reject", "CMakeLists.txt", 0,
                      f"project({project}) must be the app's folder name, {ctx.name}")
    if not catalog.NAME_RE.fullmatch(project):
        yield Finding("A2", "reject", "CMakeLists.txt", 0, f"{project!r} is not 1 to 31 of a-z, 0-9 and _")
    elif project in catalog.RESERVED:
        yield Finding("A2", "reject", "CMakeLists.txt", 0, f"{project!r} is a reserved name")


@rule("A3", "reject")
def a3_manifest(ctx):
    hits = source.manifests(ctx.app)
    if len(hits) != 1:
        yield Finding("A3", "reject", ".", 0, f"KODE_APP_MANIFEST(...) found {len(hits)} times, wanted once")
        return
    path, line, display, cats = hits[0]
    if not display or len(display) > DISPLAY_MAX:
        yield Finding("A3", "reject", path, line, f"display name of {len(display)} characters, 1 to {DISPLAY_MAX}")
    items = [c.strip() for c in cats.split(",") if c.strip()]
    if not 1 <= len(items) <= CATEGORIES_MAX:
        yield Finding("A3", "reject", path, line, f"{len(items)} categories, 1 to {CATEGORIES_MAX}")
    allowed = {c for _, c in catalog.categories(ctx.catalog)}
    for c in items:
        if c not in allowed:
            yield Finding("A3", "reject", path, line, f"category {c!r} is not in categories.txt")


def load_kappdata(directory):
    """KodeOS's kappdata.py from directory, or None when it is not there."""
    if directory is None or not (directory / "kappdata.py").is_file():
        return None
    spec = importlib.util.spec_from_file_location("kappdata", directory / "kappdata.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@rule("A4", "reject")
def a4_app_json(ctx):
    where = "appdata/app.json"
    p = ctx.app / where
    if not p.is_file():
        yield Finding("A4", "reject", where, 0, "missing")
        return
    kappdata = load_kappdata(ctx.kappdata_dir)
    if kappdata is None:
        yield Finding("A4", "reject", where, 0, "cannot validate app.json: kappdata.py not given")
        return
    try:
        obj = json.loads(p.read_text())
        kappdata.validate(obj)
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        yield Finding("A4", "reject", where, 0, str(exc))
        return
    for key in obj:
        if key not in APP_JSON_KEYS:
            yield Finding("A4", "reject", where, 0, f"key {key!r} is not allowed: only {', '.join(APP_JSON_KEYS)}")
    if kappdata.find_icon(str(ctx.app / "appdata"), obj) is None:
        yield Finding("A4", "reject", "appdata", 0, "no icon (icon.png, icon.jpg or the one app.json names)")


@rule("A5", "reject")
def a5_licence(ctx):
    p, ref = ctx.app / "LICENSE", ctx.catalog / "LICENSE"
    if not ref.is_file():
        yield Finding("A5", "reject", "LICENSE", 0, "the catalog's own LICENSE, the text to compare with, is missing")
        return
    text = p.read_text(errors="replace") if p.is_file() else ""
    if text.split() != ref.read_text(errors="replace").split():
        yield Finding("A5", "reject", "LICENSE", 0, "must be the GNU GPL version 3 text, whole and unchanged")


def version_tuple(text):
    return tuple(int(x) for x in text.split("."))


@rule("A6", "reject")
def a6_version(ctx):
    p = ctx.app / "CMakeLists.txt"
    ver = source.cmake_project_ver(p.read_text(errors="replace")) if p.is_file() else None
    if ver is None or not VERSION_RE.fullmatch(ver):
        yield Finding("A6", "reject", "CMakeLists.txt", 0,
                      f'set(PROJECT_VER "MAJOR.MINOR.PATCH") before project() is required, found {ver!r}')
        return
    old = source.cmake_project_ver(ctx.old_cmake) if ctx.old_cmake else None
    if old is None or not VERSION_RE.fullmatch(old):
        return
    if version_tuple(ver) <= version_tuple(old):
        yield Finding("A6", "reject", "CMakeLists.txt", 0, f"version {ver} must be above the catalog's {old}")


@rule("A7", "reject")
def a7_store_text(ctx):
    p = ctx.app / STORE_TEXT
    if not p.is_file():
        yield Finding("A7", "warn", STORE_TEXT, 0,
                      "missing: the marketplace page shows only app.json's one line; write what the app does and how")
        return
    text = p.read_text(errors="replace").strip()
    if not STORE_TEXT_MIN <= len(text) <= STORE_TEXT_MAX:
        yield Finding("A7", "reject", STORE_TEXT, 0,
                      f"{len(text)} characters, {STORE_TEXT_MIN} to {STORE_TEXT_MAX} wanted")
    for pattern, what in STORE_TEXT_STRIPPED:
        hit = pattern.search(text)
        if hit:
            line = text.count("\n", 0, hit.start()) + 1
            yield Finding("A7", "reject", STORE_TEXT, line,
                          f"{what}: the marketplace strips it to text; use bold, italic, code and lists")
