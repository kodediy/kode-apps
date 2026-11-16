"""Rules of block B of RULES.md: the build. B9 (the ESP-IDF version) is the workflow's."""
from __future__ import annotations

import re
from pathlib import Path

from kcheck import source
from kcheck.core import Finding, rule

TAG_RE = re.compile(r"v\d+\.\d+\.\d+")
RELEASE_WINDOW = 2
PARTITIONS = "managed_components/kodediy__kbsp/partitions.csv"
BIN_MAX = 8388608
# The most an app's ram_budget.txt may give static_max when it says why it is
# above the SDK's: the static image kodeOS ships with on the same board
# (KodeOS tools/ram_budget.txt), which boots with over 100 KB of internal heap
# left. The SDK's own static_max is its review gate, not a limit of the board.
BOARD_STATIC_MAX = 417000
EXCEPTIONS = Path(__file__).resolve().parents[1] / "board_exceptions.txt"
MODULE_SDKS = Path(__file__).resolve().parents[1] / "module_sdks.txt"
CALL_MQTT = re.compile(r"\bkode_mqtt_\w+\s*\(")


def _tag_key(tag):
    return tuple(int(x) for x in tag[1:].split("."))


# The SDK is public, so an app may fetch it over HTTPS, as the app template
# does, or over SSH, as the apps from before it went public do. Both are the
# same repository.
SDK_GITS = ("https://github.com/kodediy/kode-sdk.git", "git@github.com:kodediy/kode-sdk.git")


def _cfg(ctx):
    return source.settings(ctx.app)


def module_sdks():
    """The git URLs of tools/module_sdks.txt: the module SDKs B1 accepts."""
    return [line.strip() for line in MODULE_SDKS.read_text().splitlines()
            if line.strip() and not line.startswith("#")]


@rule("B1", "reject")
def b1_sdk_pin(ctx):
    where = "main/idf_component.yml"
    deps = source.component_deps(ctx.app)
    if "kodediy/kode" not in deps:
        yield Finding("B1", "reject", where, 0,
                      "no kodediy/kode dependency read: write each kodediy dependency in the block form, "
                      "its git, path and version on their own lines below it")
        return
    modules = module_sdks()
    sdk_versions = {}
    module_versions = {}
    for name, d in sorted(deps.items()):
        want = f"components/{name.split('/', 1)[1]}"
        git = d.get("git")
        if (git not in SDK_GITS and git not in modules) or d.get("path") != want or "override_path" in d:
            yield Finding("B1", "reject", where, 0,
                          f"{name} must come from git {' or '.join(SDK_GITS)} or a module SDK of tools/module_sdks.txt, "
                          f"path {want}, with no override_path")
            return
        if git in SDK_GITS:
            sdk_versions[name] = d.get("version", "")
        else:
            module_versions.setdefault(git, {})[name] = d.get("version", "")
    if len(set(sdk_versions.values())) != 1:
        yield Finding("B1", "reject", where, 0,
                      "every kode-sdk dependency needs the same tag: "
                      + ", ".join(f"{n} {v}" for n, v in sorted(sdk_versions.items())))
        return
    tag = sdk_versions["kodediy/kode"]
    allowed = sorted((r for r in ctx.releases if TAG_RE.fullmatch(r)), key=_tag_key, reverse=True)[:RELEASE_WINDOW]
    if not allowed:
        yield Finding("B1", "reject", where, 0, "no list of published kode-sdk releases to check the pin against")
        return
    if not TAG_RE.fullmatch(tag) or tag not in allowed:
        yield Finding("B1", "reject", where, 0, f"pin {tag!r} must be one of the newest releases: {', '.join(allowed)}")
    for git, versions in sorted(module_versions.items()):
        if len(set(versions.values())) != 1:
            yield Finding("B1", "reject", where, 0,
                          f"every dependency from {git} needs the same tag: "
                          + ", ".join(f"{n} {v}" for n, v in sorted(versions.items())))
            continue
        tag = next(iter(versions.values()))
        if tag not in ctx.module_releases.get(git, []):
            yield Finding("B1", "reject", where, 0,
                          f"pin {tag!r} of {git} must be one of its published releases")


@rule("B2", "reject")
def b2_idf_target(ctx):
    if not source.cmake_idf_target_before_project(ctx.app):
        yield Finding("B2", "reject", "CMakeLists.txt", 0, "set(IDF_TARGET esp32p4) must come before project()")


@rule("B3", "reject")
def b3_sdk_by_pin(ctx):
    cmake = ctx.app / "CMakeLists.txt"
    if cmake.is_file() and re.search(r"^\s*[^#\n]*EXTRA_COMPONENT_DIRS", cmake.read_text(errors="replace"), re.M):
        yield Finding("B3", "reject", "CMakeLists.txt", 0, "the SDK comes from the pin, not EXTRA_COMPONENT_DIRS")
    gm = ctx.app / ".gitmodules"
    if gm.is_file() and re.search(r"^\s*path\s*=\s*\S*sdk", gm.read_text(errors="replace"), re.M | re.I):
        yield Finding("B3", "reject", ".gitmodules", 0, "the SDK comes from the pin, not a submodule")
    if "kodediy/kode" not in source.component_deps(ctx.app):
        yield Finding("B3", "reject", "main/idf_component.yml", 0, "no kodediy/kode pin")
    got = _cfg(ctx).get("CONFIG_PARTITION_TABLE_CUSTOM_FILENAME")
    if got != PARTITIONS:
        yield Finding("B3", "reject", "sdkconfig.defaults", 0,
                      f"CONFIG_PARTITION_TABLE_CUSTOM_FILENAME must be {PARTITIONS!r}, found {got!r}")


@rule("B4", "reject")
def b4_app_role(ctx):
    if _cfg(ctx).get("CONFIG_KODEOS_BOOT_ROLE_APP") != "y":
        yield Finding("B4", "reject", "sdkconfig.defaults", 0, "CONFIG_KODEOS_BOOT_ROLE_APP=y is required")


DEFAULTS_ITEM_OK = re.compile(r'(\$\{KBSP_BOARD\}|(\$\{CMAKE_CURRENT_LIST_DIR\}/)?sdkconfig\.defaults)')


@rule("B5", "reject")
def b5_no_board_facts(ctx):
    for extra in sorted(ctx.app.glob("sdkconfig.defaults.*")):
        yield Finding("B5", "reject", extra.name, 0, "settings live in sdkconfig.defaults alone")
    cmake = ctx.app / "CMakeLists.txt"
    code = source._cmake_code(cmake.read_text(errors="replace")) if cmake.is_file() else ""
    for m in re.finditer(r'set\(\s*SDKCONFIG_DEFAULTS\s+"([^"]*)"', code):
        for item in m.group(1).split(";"):
            if not DEFAULTS_ITEM_OK.fullmatch(item.strip()):
                yield Finding("B5", "reject", "CMakeLists.txt", source.line_of(code, m.start()),
                              f"SDKCONFIG_DEFAULTS names {item.strip()!r}: only the board file and sdkconfig.defaults")
    if ctx.sdk is None:
        yield Finding("B5", "reject", "sdkconfig.defaults", 0, "no SDK checkout to read sdkconfig.board from")
        return
    board = set(source.read_sdkconfig(ctx.sdk / "components" / "kbsp" / "sdkconfig.board"))
    allowed = {line.strip() for line in EXCEPTIONS.read_text().splitlines()
               if line.strip() and not line.startswith("#")}
    for n, key, _ in source.sdkconfig_lines(ctx.app / "sdkconfig.defaults"):
        if key in board and key not in allowed:
            yield Finding("B5", "reject", "sdkconfig.defaults", n,
                          f"{key} belongs to the board (sdkconfig.board); do not set it here")


@rule("B6", "reject")
def b6_built_and_small(ctx):
    if ctx.build is None:
        yield Finding("B6", "reject", ".", 0, "not built")
        return
    image = ctx.build / f"{ctx.name}.bin"
    if not image.is_file():
        yield Finding("B6", "reject", ".", 0, f"not built: no {image.name}")
        return
    size = image.stat().st_size
    if size > BIN_MAX:
        yield Finding("B6", "reject", ".", 0, f"{image.name} is {size} bytes, over the {BIN_MAX} cap")


@rule("B7", "reject")
def b7_radio_and_channel(ctx):
    cfg = _cfg(ctx)
    if cfg.get("CONFIG_KODEOS_RADIO") == "n":
        for key in ("CONFIG_ESP_HOSTED_ENABLED", "CONFIG_BT_ENABLED"):
            if cfg.get(key) != "n":
                yield Finding("B7", "reject", "sdkconfig.defaults", 0, f"CONFIG_KODEOS_RADIO=n needs {key}=n too")
    if cfg.get("CONFIG_KODEOS_CHANNEL") != "n":
        for p in source.sources(ctx.app):
            code = source.strip_code(p.read_text(errors="replace"))
            m = CALL_MQTT.search(code)
            if m:
                yield Finding("B7", "reject", source.rel(ctx.app, p), source.line_of(code, m.start()),
                              "an app that calls kode_mqtt_* sets CONFIG_KODEOS_CHANNEL=n")
                return


def _static_max(path):
    if not path.is_file():
        return None
    m = re.search(r"^\s*static_max\s+(\d+)", path.read_text(), re.M)
    return int(m.group(1)) if m else None


def _static_max_why(path):
    m = re.search(r"^\s*static_max_why\s+(\S.*)$", path.read_text(), re.M)
    return m.group(1).strip() if m else None


@rule("B8", "reject")
def b8_ram_budget(ctx):
    budget = ctx.app / "ram_budget.txt"
    if not budget.is_file():
        yield Finding("B8", "reject", "ram_budget.txt", 0, "missing")
        return
    mine = _static_max(budget)
    theirs = _static_max(ctx.sdk / "tests" / "target" / "ram_budget.txt") if ctx.sdk else None
    if mine is None:
        yield Finding("B8", "reject", "ram_budget.txt", 0, "no static_max line")
    elif theirs is None:
        yield Finding("B8", "reject", "ram_budget.txt", 0, "no SDK budget to compare static_max with")
    elif mine > BOARD_STATIC_MAX:
        yield Finding("B8", "reject", "ram_budget.txt", 0,
                      f"static_max {mine} is above the board's {BOARD_STATIC_MAX}")
    elif mine > theirs and _static_max_why(budget) is None:
        yield Finding("B8", "reject", "ram_budget.txt", 0,
                      f"static_max {mine} is above the SDK's {theirs} with no static_max_why line")
    if ctx.build is None:
        return
    if ctx.ram_checker is None:
        yield Finding("B8", "reject", "ram_budget.txt", 0, "no RAM check available")
        return
    ok, out = ctx.ram_checker(ctx.build / f"{ctx.name}.elf", budget)
    if not ok:
        yield Finding("B8", "reject", "ram_budget.txt", 0, f"check_ram.sh failed: {out}")
