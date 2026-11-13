"""Plain int/unsigned/long/short declarations in C sources (rule E9).

    python basic_types.py DIR...             counts per file
    SHOW=1 python basic_types.py DIR...      every line
    python basic_types.py --findings DIR...  "E9 <file>:<line> <text>" per line
"""
import collections
import os
import re
import sys

# Folders never scanned, matched as whole path components.
SKIP_DIRS = {'qpc', 'rfal', 'managed_components', 'build', '.git'}
# Generated files, matched as substrings of the path.
SKIP_PARTS = ('/fonts/src/', '/images/src/', '/kody/src/kody_', 'kui_tokens.h')
# a declaration: a basic type word not inside a cast "(type)" nor "sizeof(type"
decl = re.compile(r'(?<![\w])(?:const\s+)?(unsigned\s+long\s+long|unsigned\s+long|unsigned\s+int|unsigned\s+char|unsigned\s+short|unsigned|signed\s+char|long\s+long|long|short|int)\b(?!\s*\))\s*(?:const\s+)?\**\s*[A-Za-z_]\w*')


def scan_file(p):
    """(line, text) of each line of p that declares with a plain basic type."""
    hits = []
    inblock = False
    with open(p, errors='ignore') as f:
        lines = f.readlines()
    for n, line in enumerate(lines, 1):
        code = line
        # strip comments
        if inblock:
            if '*/' in code:
                code = code.split('*/', 1)[1]
                inblock = False
            else:
                continue
        code = re.sub(r'/\*.*?\*/', '', code)
        if '/*' in code:
            code = code.split('/*')[0]
            inblock = True
        code = code.split('//')[0]
        code = re.sub(r'"(?:\\.|[^"\\])*"', '""', code)
        if re.match(r'\s*#', code):
            continue
        code = re.sub(r'\(\s*(?:const\s+)?(?:unsigned|signed|int|long|short)(?:\s+(?:long|int|char|short))*\s*\**\s*\)', ' ', code)
        code = re.sub(r'sizeof\s*\([^)]*\)', ' ', code)
        if decl.search(code):
            hits.append((n, line.rstrip()))
    return hits


def scan(roots):
    """{path: [(line, text), ...]} for every C/C++ file under roots with a hit."""
    hits = collections.defaultdict(list)
    for root in roots:
        for d, dirs, fs in os.walk(root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for f in fs:
                if not f.endswith(('.c', '.h', '.cpp', '.hpp')):
                    continue
                p = os.path.join(d, f)
                if any(s in p for s in SKIP_PARTS):
                    continue
                found = scan_file(p)
                if found:
                    hits[p].extend(found)
    return dict(hits)


def main(argv):
    findings = '--findings' in argv
    hits = scan([a for a in argv if a != '--findings'])
    if findings:
        for p in sorted(hits):
            for n, line in hits[p]:
                print(f"E9 {p}:{n} {line.strip()}")
        return
    if os.environ.get("SHOW"):
        for p in sorted(hits):
            for n, line in hits[p]:
                print(f"{p}:{n}: {line.strip()}")
        return
    tot = 0
    for p in sorted(hits, key=lambda k: -len(hits[k])):
        tot += len(hits[p])
        print(f'{len(hits[p]):4d} {p}')
    print('total', tot, 'files', len(hits))


if __name__ == "__main__":
    main(sys.argv[1:])
