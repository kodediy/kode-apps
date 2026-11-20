"""What the marketplace lists for an app, read from the app the catalog pins.

Nothing here judges or sends: publish_app.py sends it, after the rules have
passed on the same commit. Every field comes from a file the rules already
check, so a listing never says what the app does not.
"""
from __future__ import annotations

import json
from pathlib import Path

from kcheck import source
from kcheck.rules_a import load_kappdata

GITHUB = "https://github.com/kodediy/kode-app-"
COVER_EXT = (".png", ".jpg", ".jpeg")  # the icons kappdata finds that the marketplace takes as a cover
# What a transparent icon is laid on for the cover when app.json names no
# colour: the black page kodeOS draws an app's disc on.
COVER_GROUND = "#000000"
# The categories the marketplace takes; it refuses any other word.
MARKETPLACE_CATEGORIES = ("game", "tool", "communication", "wireless", "creative", "maker", "ai")
# The catalog's categories (categories.txt) in the marketplace's own list.
CATEGORY_MAP = {
    "ai": "ai",
    "communication": "communication",
    "games": "game",
    "media": "creative",
    "tools": "tool",
    "wireless": "wireless",
}


def slug(name: str) -> str:
    """The marketplace's id for the app: its name with `-` for `_`, the one character a slug refuses."""
    return name.replace("_", "-")


def listing(app: Path, kappdata_dir: Path | None) -> dict:
    """The fields of the app's listing; the icon is a path, the colour is what the cover is laid on.

    Raises ValueError when the app has no single manifest, no version, no
    app.json or no icon: the rules refuse all four, so a listing never guesses.
    """
    name = app.resolve().name
    hits = source.manifests(app)
    if len(hits) != 1:
        raise ValueError(f"{name}: KODE_APP_MANIFEST(...) found {len(hits)} times, wanted once")
    _, _, display, cats = hits[0]
    first = next((c.strip() for c in cats.split(",") if c.strip()), "")
    if first not in CATEGORY_MAP:
        raise ValueError(f"{name}: category {first!r} has no marketplace category in CATEGORY_MAP")
    cmake = app / "CMakeLists.txt"
    version = source.cmake_project_ver(cmake.read_text(errors="replace")) if cmake.is_file() else None
    if not version:
        raise ValueError(f"{name}: no set(PROJECT_VER ...) in CMakeLists.txt")
    app_json = app / "appdata" / "app.json"
    if not app_json.is_file():
        raise ValueError(f"{name}: no appdata/app.json")
    obj = json.loads(app_json.read_text())
    kappdata = load_kappdata(kappdata_dir)
    if kappdata is None:
        raise ValueError(f"{name}: kappdata.py not found, it finds the icon")
    icon = kappdata.find_icon(str(app / "appdata"), obj)
    if icon is None or Path(icon).suffix.lower() not in COVER_EXT:
        raise ValueError(f"{name}: no PNG or JPEG icon in appdata/ for the cover")
    return {
        "slug": slug(name),
        "name": display,
        "version": version,
        "category": CATEGORY_MAP[first],
        "description": obj.get("description", ""),
        "githubUrl": GITHUB + name,
        "icon": Path(icon),
        "color": obj.get("color", COVER_GROUND),
    }
