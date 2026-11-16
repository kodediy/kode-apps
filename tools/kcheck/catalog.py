"""The catalog's own checks, and which apps a pull request changes or a maintainer names.

A1: every submodule is `apps/<name>` with the relative URL `../kode-app-<name>.git`.
A2: every name is a valid, unreserved project name, used once.
A3: categories.txt exists and lists valid categories, each once.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from kcheck.core import Finding

NAME_RE = re.compile(r"[a-z0-9_]{1,31}")
RESERVED = ("kodeos", "c5_slave")
CATEGORY_RE = re.compile(r"[a-z0-9_-]{1,15}")
GITLINK = "160000"


@dataclass(frozen=True)
class Change:
    name: str
    old: str | None
    new: str | None


def submodules(catalog: Path) -> list[tuple[str, str, str]]:
    """(section, path, url) of each submodule in .gitmodules."""
    gm = catalog / ".gitmodules"
    if not gm.is_file():
        return []
    r = subprocess.run(["git", "config", "-f", str(gm), "--get-regexp", r"^submodule\..*\.(path|url)$"],
                       capture_output=True, text=True)
    entries: dict[str, dict[str, str]] = {}
    for line in r.stdout.splitlines():
        key, _, value = line.partition(" ")
        section, _, field = key[len("submodule."):].rpartition(".")
        entries.setdefault(section, {})[field] = value
    return [(s, e.get("path", ""), e.get("url", "")) for s, e in entries.items()]


def tracked_under_apps(catalog: Path) -> list[tuple[str, str]]:
    """(mode, path) of every entry git tracks under apps/; none outside a git work tree."""
    r = subprocess.run(["git", "-C", str(catalog), "ls-files", "-s", "--", "apps/"],
                       capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines() if r.returncode == 0 else []:
        meta, _, path = line.partition("\t")
        out.append((meta.split(" ")[0], path))
    return out


def categories(catalog: Path) -> list[tuple[int, str]]:
    p = catalog / "categories.txt"
    if not p.is_file():
        return []
    return [(n, line.strip()) for n, line in enumerate(p.read_text().splitlines(), 1)
            if line.strip() and not line.strip().startswith("#")]


def check_catalog(catalog: Path) -> list[Finding]:
    found = []
    seen = set()
    for section, path, url in submodules(catalog):
        where = f"submodule {section}"
        m = re.fullmatch(r"apps/([^/]+)", path)
        if not m:
            found.append(Finding("A1", "reject", ".gitmodules", 0, f"{where}: path {path!r} is not apps/<name>"))
            continue
        name = m.group(1)
        if url != f"../kode-app-{name}.git":
            found.append(Finding("A1", "reject", ".gitmodules", 0,
                                 f"{where}: url {url!r} must be ../kode-app-{name}.git"))
        if not NAME_RE.fullmatch(name):
            found.append(Finding("A2", "reject", ".gitmodules", 0,
                                 f"{where}: {name!r} is not 1 to 31 of a-z, 0-9 and _"))
        elif name in RESERVED:
            found.append(Finding("A2", "reject", ".gitmodules", 0, f"{where}: {name!r} is reserved"))
        if name in seen:
            found.append(Finding("A2", "reject", ".gitmodules", 0, f"{where}: {name!r} is in the catalog twice"))
        seen.add(name)
    paths = {path for _, path, _ in submodules(catalog)}
    for mode, path in tracked_under_apps(catalog):
        if mode != GITLINK:
            found.append(Finding("A1", "reject", path, 0, "only submodules live under apps/, not files"))
        elif path not in paths:
            found.append(Finding("A1", "reject", path, 0, "a submodule with no entry in .gitmodules"))
    if not (catalog / "categories.txt").is_file():
        found.append(Finding("A3", "reject", "categories.txt", 0, "the category list is missing"))
    listed = set()
    for n, cat in categories(catalog):
        if not CATEGORY_RE.fullmatch(cat):
            found.append(Finding("A3", "reject", "categories.txt", n,
                                 f"{cat!r} is not 1 to 15 of a-z, 0-9, _ and -"))
        if cat in listed:
            found.append(Finding("A3", "reject", "categories.txt", n, f"{cat!r} is listed twice"))
        listed.add(cat)
    return found


def changed_apps(catalog: Path, base: str, head: str) -> list[Change]:
    """The gitlinks under apps/ that head adds, moves or removes since it left base."""
    out = subprocess.run(["git", "-C", str(catalog), "diff", "--raw", "--no-abbrev", f"{base}...{head}", "--", "apps/"],
                         check=True, capture_output=True, text=True).stdout
    changes = []
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        old_mode, new_mode, old_sha, new_sha, _ = meta.lstrip(":").split(" ", 4)
        if GITLINK not in (old_mode, new_mode):
            continue
        old = old_sha if old_mode == GITLINK else None
        new = new_sha if new_mode == GITLINK else None
        changes.append(Change(path.split("/", 1)[1], old, new))
    return changes


def named_apps(catalog: Path, names: list[str], head: str = "HEAD") -> list[Change]:
    """Each named app at the commit head pins, as a change from nothing.

    A run started by hand checks and publishes these again. A name that is not
    an app of head, or is named twice, raises ValueError before any is listed.
    """
    changes = []
    for name in names:
        if not NAME_RE.fullmatch(name):
            raise ValueError(f"{name!r} is not an app name")
        if any(c.name == name for c in changes):
            raise ValueError(f"{name!r} is named twice")
        out = subprocess.run(["git", "-C", str(catalog), "ls-tree", head, "--", f"apps/{name}"],
                             check=True, capture_output=True, text=True).stdout
        meta, _, path = out.strip().partition("\t")
        fields = meta.split(" ")
        if path != f"apps/{name}" or len(fields) != 3 or fields[0] != GITLINK:
            raise ValueError(f"{name!r} is not an app of the catalog")
        changes.append(Change(name, None, fields[2]))
    return changes
