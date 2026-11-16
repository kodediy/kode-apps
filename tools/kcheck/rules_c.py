"""Rules of block C of RULES.md: behaviour at run time.

C1, C4, C6, C9 and C10 are judged by the reviewer and have no function here.
Every pattern runs on code with its comments and literals blanked, so a
comment that names a call never matches.
"""
from __future__ import annotations

import json
import re

from kcheck import source
from kcheck.core import Finding, rule

AO_FILE = re.compile(r"QState\s+\w+\s*\([^)]*QEvt\s+const\s*\*")
# Each name is one the SDK or FreeRTOS declares: a name nobody declares never matches.
BLOCKING = ("kode_delay", "kode_net_ping", "kode_http_get", "kode_udp_send", "kode_net_resolve",
            "kode_imu_read", "vTaskDelay", "xSemaphoreTake", "khal_sem_wait_timeout", "kode_nfc_read",
            "kode_nfc_read_id", "kode_rfid_read_id")
BLOCKING_RE = re.compile(r"\b(" + "|".join(BLOCKING) + r")\s*\(")
OWNED_INCLUDES = ("driver/i2s", "esp_lcd", "esp_codec_dev", "esp_wifi", "nimble/", "host/ble_",
                  "sdmmc_", "driver/sdmmc")
INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)
OWN_SIGNALS_RE = re.compile(r"enum\s*\w*\s*\{\s*(\w+)\s*=\s*MAX_SIG\b([^}]*)\}")
PUBLISH_RE = re.compile(r"\b(QACTIVE_PUBLISH|QF_PUBLISH)\s*\(")
START_RE = re.compile(r"\bQACTIVE_START\s*\(\s*([^,]+),")
NAME_ATTR_RE = re.compile(r"\bQActive_setAttr\s*\(\s*([^,]+),\s*TASK_NAME_ATTR\b")
WORKER_RE = re.compile(r"\bkode_worker_start\s*\(")
DEFINE_RE = re.compile(r"^\s*#\s*define\s+(\w+)\s+\(?\s*(\d+)[uUlL]*\s*\)?\s*$", re.M)
WORKER_STACK_MIN = 8192
BOOT_CALL_RE = re.compile(r"\b(esp_ota_\w+|esp_partition_write(?:_raw)?|esp_partition_erase_range"
                          r"|esp_flash_write\w*|esp_flash_erase_\w+|spi_flash_write\w*|spi_flash_erase_\w+)\s*\(")
GITLEAKS_CONFIGS = (".gitleaks.toml", ".gitleaks.yaml", ".gitleaks.yml")
INLINE_ALLOW = "gitleaks:allow"


def _code(ctx):
    """(relative path, stripped code) of every source."""
    return [(source.rel(ctx.app, p), source.strip_code(p.read_text(errors="replace")))
            for p in source.sources(ctx.app)]


def _args(code, open_paren):
    """The top-level arguments of the call whose '(' is at open_paren, and the offset after ')'."""
    depth, start, args = 0, open_paren + 1, []
    for i in range(open_paren, len(code)):
        c = code[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                args.append(code[start:i].strip())
                return args, i + 1
        elif c == "," and depth == 1:
            args.append(code[start:i].strip())
            start = i + 1
    return args, len(code)


@rule("C2", "warn")
def c2_never_block(ctx):
    if source.settings(ctx.app).get("CONFIG_KQP_AO_WATCH") == "n":
        yield Finding("C2", "reject", "sdkconfig.defaults", 0, "CONFIG_KQP_AO_WATCH=n turns off the AO watchdog")
    for path, code in _code(ctx):
        if not AO_FILE.search(code):
            continue
        for m in BLOCKING_RE.finditer(code):
            yield Finding("C2", "warn", path, source.line_of(code, m.start()),
                          f"{m.group(1)}() blocks; in an Active Object it belongs on a kode_worker")


@rule("C3", "warn")
def c3_owned_devices(ctx):
    for p in source.sources(ctx.app):
        text = source.strip_comments(p.read_text(errors="replace"))
        for m in INCLUDE_RE.finditer(text):
            if m.group(1).startswith(OWNED_INCLUDES):
                yield Finding("C3", "warn", source.rel(ctx.app, p), source.line_of(text, m.start()),
                              f"{m.group(1)} drives a device that an SDK Active Object owns; ask the owner")


@rule("C5", "warn")
def c5_own_signals_posted(ctx):
    texts = [(source.rel(ctx.app, p), source.strip_comments(p.read_text(errors="replace")))
             for p in source.sources(ctx.app)]
    own = set()
    for _, text in texts:
        for m in OWN_SIGNALS_RE.finditer(text):
            own.add(m.group(1))
            own.update(re.findall(r"\b([A-Z]\w*_SIG)\b", m.group(2)))
    if not own:
        return
    for path, text in texts:
        for m in PUBLISH_RE.finditer(text):
            args, _ = _args(text, m.end() - 1)
            used = [s for s in own if re.search(rf"\b{s}\b", " ".join(args))]
            if used:
                yield Finding("C5", "warn", path, source.line_of(text, m.start()),
                              f"{used[0]} is the app's own signal: post it, never publish it")


@rule("C7", "reject")
def c7_task_names(ctx):
    for path, code in _code(ctx):
        for m in START_RE.finditer(code):
            target = re.sub(r"\s+", "", m.group(1))
            named = any(re.sub(r"\s+", "", n.group(1)) == target
                        for n in NAME_ATTR_RE.finditer(code, 0, m.start()))
            if not named:
                yield Finding("C7", "reject", path, source.line_of(code, m.start()),
                              f"QACTIVE_START({target}) without an earlier QActive_setAttr(..., TASK_NAME_ATTR, ...)")


@rule("C8", "warn")
def c8_worker_stack(ctx):
    defines = {}
    for p in source.sources(ctx.app):
        for m in DEFINE_RE.finditer(source.strip_comments(p.read_text(errors="replace"))):
            defines[m.group(1)] = int(m.group(2))
    for path, code in _code(ctx):
        for m in WORKER_RE.finditer(code):
            args, _ = _args(code, m.end() - 1)
            if len(args) < 4:
                continue
            stack = args[3]
            num = re.fullmatch(r"(\d+)[uUlL]*", stack)
            value = int(num.group(1)) if num else defines.get(stack)
            if value is not None and value < WORKER_STACK_MIN:
                yield Finding("C8", "warn", path, source.line_of(code, m.start()),
                              f"worker stack {stack} = {value} bytes, under {WORKER_STACK_MIN}")


@rule("C11", "reject")
def c11_secrets(ctx):
    for name in GITLEAKS_CONFIGS:
        if (ctx.app / name).is_file():
            yield Finding("C11", "reject", name, 0, "the scanner's settings are the catalog's, not the app's")
    for p in sorted(ctx.app.rglob("*")):
        rel = p.relative_to(ctx.app)
        if p.is_file() and not set(rel.parts) & set(source.SKIP_DIRS):
            for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if INLINE_ALLOW in line:
                    yield Finding("C11", "reject", rel.as_posix(), n,
                                  f"{INLINE_ALLOW} hides a finding; list it in .gitleaksignore for review instead")
    if ctx.secrets_report is None:
        yield Finding("C11", "warn", ".", 0, "not scanned for secrets: no --secrets-report given")
    else:
        if not ctx.secrets_report.is_file():
            yield Finding("C11", "reject", ".", 0, "no secret scan report")
        else:
            for leak in json.loads(ctx.secrets_report.read_text() or "[]") or []:
                yield Finding("C11", "reject", leak.get("File", "."), int(leak.get("StartLine", 0)),
                              f"{leak.get('RuleID', 'secret')} in {str(leak.get('Commit', ''))[:12]}")
    ignore = ctx.app / ".gitleaksignore"
    if ignore.is_file():
        for n, line in enumerate(ignore.read_text().splitlines(), 1):
            if line.strip() and not line.startswith("#"):
                yield Finding("C11", "warn", ".gitleaksignore", n,
                              f"ignored: {line.strip()} (needs a maintainer's approval)")


@rule("C12", "reject")
def c12_boot_model(ctx):
    for path, code in _code(ctx):
        for m in BOOT_CALL_RE.finditer(code):
            yield Finding("C12", "reject", path, source.line_of(code, m.start()),
                          f"{m.group(1)}() touches otadata or the partitions; an app never does")
