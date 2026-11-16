#!/usr/bin/env python3
"""The catalog's rule script: check one app, or the catalog itself.

    check_app.py check --app DIR --catalog DIR [--build DIR] [--sdk DIR]
                       [--releases FILE] [--module-releases FILE] [--old-cmake FILE]
                       [--kappdata-dir DIR]
                       [--secrets-report FILE] [--output FILE]
    check_app.py catalog --catalog DIR [--base SHA --head SHA | --apps NAME...]
    check_app.py sdk-tag APP        the kodediy/kode tag the app pins
    check_app.py version APP        the app's PROJECT_VER

`check` prints one line per finding, `<id> <level> <path>:<line> <message>`,
then a summary, and exits 1 when any finding is a reject. It reads files
only; the workflow fetches everything first.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kcheck import core, source  # noqa: E402


def ram_checker(sdk: Path):
    """Run the pinned SDK's check_ram.sh on an ELF and a budget file."""
    def check(elf: Path, budget: Path):
        script = sdk / "tools" / "check_ram.sh"
        r = subprocess.run(["bash", str(script), str(elf), str(budget)], capture_output=True, text=True)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    return check


def existing_dir(text):
    p = Path(text)
    if not p.is_dir():
        raise argparse.ArgumentTypeError(f"not a directory: {text}")
    return p


def cmd_check(a) -> int:
    releases = []
    if a.releases:
        releases = [r["tagName"] for r in json.loads(Path(a.releases).read_text())]
    module_releases = {}
    if a.module_releases:
        module_releases = json.loads(Path(a.module_releases).read_text())
    old = Path(a.old_cmake).read_text(errors="replace") if a.old_cmake and Path(a.old_cmake).is_file() else None
    ctx = core.Context(app=a.app, name=a.app.resolve().name, catalog=a.catalog, build=a.build,
                       sdk=a.sdk, releases=releases, module_releases=module_releases, old_cmake=old, kappdata_dir=a.kappdata_dir,
                       secrets_report=Path(a.secrets_report) if a.secrets_report else None,
                       ram_checker=ram_checker(a.sdk) if a.sdk else None)
    found = core.run(ctx)
    lines = [f.format() for f in found]
    rejects = sum(1 for f in found if f.level == "reject")
    lines.append(f"{rejects} reject, {len(found) - rejects} warn")
    print("\n".join(lines))
    if a.output:
        Path(a.output).write_text("\n".join(lines) + "\n")
    return core.exit_code(found)


def cmd_catalog(a) -> int:
    from kcheck import catalog
    found = catalog.check_catalog(a.catalog)
    for f in found:
        print(f.format())
    if a.apps:
        try:
            changes = catalog.named_apps(a.catalog, a.apps)
        except ValueError as exc:
            print(f"--apps: {exc}", file=sys.stderr)
            return 2
    elif a.base and a.head:
        changes = catalog.changed_apps(a.catalog, a.base, a.head)
    else:
        changes = []
    for c in changes:
        print(f"change {c.name} {c.old or '-'} {c.new or '-'}")
    return core.exit_code(found)


def cmd_sdk_tag(a) -> int:
    tag = source.component_deps(a.app).get("kodediy/kode", {}).get("version")
    if not tag:
        print("no kodediy/kode version in main/idf_component.yml", file=sys.stderr)
        return 1
    print(tag)
    return 0


def cmd_version(a) -> int:
    p = a.app / "CMakeLists.txt"
    ver = source.cmake_project_ver(p.read_text(errors="replace")) if p.is_file() else None
    if not ver:
        print("no set(PROJECT_VER ...) in CMakeLists.txt", file=sys.stderr)
        return 1
    print(ver)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--app", type=existing_dir, required=True)
    c.add_argument("--catalog", type=existing_dir, required=True)
    c.add_argument("--build", type=existing_dir)
    c.add_argument("--sdk", type=existing_dir)
    c.add_argument("--releases")
    c.add_argument("--module-releases")
    c.add_argument("--old-cmake")
    c.add_argument("--kappdata-dir", type=existing_dir)
    c.add_argument("--secrets-report")
    c.add_argument("--output")
    k = sub.add_parser("catalog")
    k.add_argument("--catalog", type=existing_dir, required=True)
    k.add_argument("--base")
    k.add_argument("--head")
    k.add_argument("--apps", nargs="+", metavar="NAME",
                   help="list these apps of HEAD as added, to check and publish them again")
    for name in ("sdk-tag", "version"):
        s = sub.add_parser(name)
        s.add_argument("app", type=existing_dir)
    a = ap.parse_args(argv)
    return {"check": cmd_check, "catalog": cmd_catalog, "sdk-tag": cmd_sdk_tag,
            "version": cmd_version}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
