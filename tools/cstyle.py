"""Mechanical C style pass for the kodeOS review.

    python cstyle.py blocks FILE...   brace on its own line, ( cond ) spacing
    python cstyle.py yoda FILE...     constant/value left, variable right
    python cstyle.py check A B        same tokens ignoring whitespace? (exit 1 if not)
    python cstyle.py lint FILE...     report E6/E7/E8 as "<id> <file>:<line> <what>", exit 1 if any

Rewrites files in place and prints a summary plus every spot it left alone
for a human (one-line blocks, multi-line operands).
"""
import difflib
import re
import sys

OPS = sorted("""
>>= <<= ... -> ++ -- << >> <= >= == != && || += -= *= /= %= &= ^= |= ##
""".split(), key=len, reverse=True)
TOKEN = re.compile(
    r"(?P<ws>[ \t]+)|(?P<nl>\r?\n)|(?P<cmt>/\*.*?\*/|//[^\n]*)"
    r"|(?P<str>\"(?:\\.|[^\"\\\n])*\")|(?P<chr>'(?:\\.|[^'\\\n])*')"
    r"|(?P<num>\.?\d(?:[\w.]|[eEpP][+-])*)|(?P<id>[A-Za-z_]\w*)"
    r"|(?P<op>" + "|".join(re.escape(o) for o in OPS) + r"|[^\s])",
    re.S)


class Tok:
    __slots__ = ("kind", "text", "line")

    def __init__(self, kind, text, line):
        self.kind, self.text, self.line = kind, text, line

    def __repr__(self):
        return f"{self.kind}:{self.text!r}@{self.line}"


def tokenize(src):
    """Tokens of src; a preprocessor directive (with continuations) is one 'pp' token."""
    toks, i, line, bol = [], 0, 1, True
    while i < len(src):
        if bol:
            m = re.match(r"[ \t]*#", src[i:])
            if m:
                j = i
                while True:
                    k = src.find("\n", j)
                    if k == -1:
                        k = len(src)
                        break
                    if src[k - 1] == "\\":
                        j = k + 1
                        continue
                    break
                text = src[i:k]
                toks.append(Tok("pp", text, line))
                line += text.count("\n")
                i = k
                bol = False
                continue
        m = TOKEN.match(src, i)
        kind = m.lastgroup
        text = m.group(kind)
        toks.append(Tok(kind, text, line))
        line += text.count("\n")
        i = m.end()
        if kind == "nl":
            bol = True
        elif kind not in ("ws",) and not (kind == "cmt" and "\n" not in text and False):
            bol = False
    assert "".join(t.text for t in toks) == src
    return toks


def significant(toks):
    return [t.text for t in toks if t.kind not in ("ws", "nl", "cmt")]


def indent_of(toks, idx):
    """Indentation of the line that holds toks[idx]."""
    j = idx
    while j > 0 and toks[j - 1].kind != "nl":
        j -= 1
    if toks[j].kind == "ws":
        return toks[j].text
    return ""


def match_paren(toks, idx, open_="(", close=")"):
    depth = 0
    for j in range(idx, len(toks)):
        if toks[j].text == open_ and toks[j].kind == "op":
            depth += 1
        elif toks[j].text == close and toks[j].kind == "op":
            depth -= 1
            if depth == 0:
                return j
    return -1


def next_sig(toks, idx, same_line=False):
    j = idx + 1
    while j < len(toks):
        k = toks[j].kind
        if k == "nl" and same_line:
            return -1
        if k not in ("ws", "nl", "cmt"):
            return j
        j += 1
    return -1


def prev_sig(toks, idx):
    j = idx - 1
    while j >= 0 and toks[j].kind in ("ws", "nl", "cmt"):
        j -= 1
    return j


# --------------------------------------------------------------------------
# Pass 1: braces on their own line, one space inside the condition's parens
# --------------------------------------------------------------------------

def fix_parens(toks, op, cp, notes, path):
    """One space after ( and before ) of a control condition."""
    # after the open paren
    if toks[op + 1].kind == "ws":
        toks[op + 1].text = " "
    elif toks[op + 1].kind != "nl":
        toks.insert(op + 1, Tok("ws", " ", toks[op].line))
        cp += 1
    # before the close paren: only when it shares a line with the last operand
    before = cp - 1
    if toks[before].kind == "ws":
        if toks[before - 1].kind != "nl":
            toks[before].text = " "
    elif toks[before].kind != "nl":
        toks.insert(cp, Tok("ws", " ", toks[cp].line))
        cp += 1
    return cp


def brace_down(toks, after, indent, notes, path, what):
    """If a '{' follows toks[after] on the same line, move it to its own line.

    Returns the number of tokens inserted (to keep indices honest) or 0."""
    b = next_sig(toks, after, same_line=True)
    if b == -1 or toks[b].text != "{":
        return 0
    # Anything but a comment after the brace on that line: leave for a human.
    k = next_sig(toks, b, same_line=True)
    if k != -1:
        notes.append(f"{path}:{toks[b].line}: one-line block after {what}, left as is")
        return 0
    # replace the whitespace between `after` and `{` by newline + indent
    start = after + 1
    # drop everything between (only whitespace may be there; a comment stays)
    between = toks[start:b]
    if any(t.kind == "cmt" for t in between):
        notes.append(f"{path}:{toks[b].line}: comment before brace after {what}, left as is")
        return 0
    del toks[start:b]
    new = [Tok("nl", "\n", toks[after].line)]
    if indent:
        new.append(Tok("ws", indent, toks[after].line))
    toks[start:start] = new
    return len(new) - len(between)


def pass_blocks(src, path, notes):
    toks = tokenize(src)
    i = 0
    changed = 0
    while i < len(toks):
        t = toks[i]
        if t.kind != "id" or t.text not in ("if", "for", "while", "switch", "else", "do"):
            i += 1
            continue
        indent = indent_of(toks, i)
        if t.text == "else":
            p = prev_sig(toks, i)
            # `} else` on one line: split it
            if p >= 0 and toks[p].text == "}" and toks[p].line == t.line:
                del toks[p + 1:i]
                ind = indent_of(toks, p)
                toks[p + 1:p + 1] = [Tok("nl", "\n", t.line)] + ([Tok("ws", ind, t.line)] if ind else [])
                i = p + 1 + (2 if ind else 1)
                indent = ind
                changed += 1
            n = next_sig(toks, i, same_line=True)
            if n != -1 and toks[n].text == "if":
                i = n          # the if rule handles the rest
                continue
            changed += bool(brace_down(toks, i, indent, notes, path, "else"))
            i += 1
            continue
        if t.text == "do":
            changed += bool(brace_down(toks, i, indent, notes, path, "do"))
            i += 1
            continue
        op = next_sig(toks, i)
        if op == -1 or toks[op].text != "(":
            i += 1
            continue
        # exactly one space between keyword and (
        if op == i + 1:
            toks.insert(i + 1, Tok("ws", " ", t.line))
            op += 1
        elif toks[i + 1].kind == "ws" and op == i + 2:
            toks[i + 1].text = " "
        cp = match_paren(toks, op)
        if cp == -1:
            i += 1
            continue
        old = "".join(x.text for x in toks[op:cp + 1])
        cp = fix_parens(toks, op, cp, notes, path)
        if "".join(x.text for x in toks[op:cp + 1]) != old:
            changed += 1
        # `if (...) {` -> brace on its own line, indented as the keyword's line
        # (for `else if`, the keyword's line now starts with `else`)
        changed += bool(brace_down(toks, cp, indent, notes, path, t.text))
        i = cp + 1
    return "".join(x.text for x in toks), changed


# --------------------------------------------------------------------------
# Pass 2: constant or value on the left of a comparison, variable on the right
# --------------------------------------------------------------------------

CMP = {"==": "==", "!=": "!=", "<": ">", ">": "<", "<=": ">=", ">=": "<="}
STOP_LEFT = {",", ";", "{", "}", "?", ":", "&&", "||", "=", "+=", "-=", "*=",
             "/=", "%=", "&=", "^=", "|=", "<<=", ">>="}
STOP_KW = {"return", "case", "if", "while", "for", "switch", "else", "do"}
LOWER = {"&", "|", "^", "==", "!=", "<", ">", "<=", ">=", "?", ":"}
CONST_ID = re.compile(r"^(NULL|true|false|[A-Z][A-Z0-9_]*)$")
TYPE_WORDS = {"const", "volatile", "unsigned", "signed", "char", "short", "int",
              "long", "float", "double", "void", "bool", "struct", "enum", "union"}


def sig_index(toks):
    return [k for k, t in enumerate(toks) if t.kind not in ("ws", "nl", "cmt")]


def operand_left(toks, sig, s):
    """Indices (into sig) [a, s) of the left operand ending before sig[s]."""
    depth = 0
    a = s
    while a > 0:
        t = toks[sig[a - 1]]
        x = t.text
        if t.kind == "pp":
            return None
        if x in (")", "]"):
            depth += 1
        elif x in ("(", "["):
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and (x in STOP_LEFT or (t.kind == "id" and x in STOP_KW)):
            break
        elif depth == 0 and x in LOWER and t.kind == "op":
            return None
        a -= 1
    return a if a < s else None


def operand_right(toks, sig, s):
    """Indices (into sig) (s, b] of the right operand after sig[s]."""
    depth = 0
    b = s
    while b + 1 < len(sig):
        t = toks[sig[b + 1]]
        x = t.text
        if t.kind == "pp":
            return None
        if x in ("(", "["):
            depth += 1
        elif x in (")", "]"):
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and (x in STOP_LEFT or (t.kind == "id" and x in STOP_KW)):
            break
        elif depth == 0 and x in LOWER and t.kind == "op":
            return None
        b += 1
    return b if b > s else None


def is_lvalue(texts, kinds):
    """A postfix chain from a variable: x, x[i], x.y, p->y, f(x)->y, *p, (x)."""
    n = len(texts)
    if n == 0:
        return False
    # strip one level of wrapping parentheses
    if texts[0] == "(" and texts[-1] == ")":
        depth = 0
        whole = True
        for k, x in enumerate(texts):
            depth += x == "("
            depth -= x == ")"
            if depth == 0 and k < n - 1:
                whole = False
                break
        if whole:
            inner_t, inner_k = texts[1:-1], kinds[1:-1]
            # a cast is not an lvalue: (type)x
            return is_lvalue(inner_t, inner_k)
    k = 0
    while k < n and texts[k] == "*":
        k += 1
    if k >= n or kinds[k] != "id" or texts[k] in TYPE_WORDS or texts[k] == "sizeof":
        return False
    head_const = CONST_ID.match(texts[k]) is not None
    k += 1
    last_call = False
    accessed = False
    while k < n:
        x = texts[k]
        if x in (".", "->"):
            if k + 1 >= n or kinds[k + 1] != "id":
                return False
            k += 2
            accessed = True
            last_call = False
        elif x == "[":
            depth = 0
            while k < n:
                depth += texts[k] == "["
                depth -= texts[k] == "]"
                k += 1
                if depth == 0:
                    break
            accessed = True
            last_call = False
        elif x == "(":
            depth = 0
            while k < n:
                depth += texts[k] == "("
                depth -= texts[k] == ")"
                k += 1
                if depth == 0:
                    break
            last_call = True
        else:
            return False
    if last_call:
        return False
    if head_const and not accessed:
        return False
    return True


def pass_yoda(src, path, notes):
    """Swap until nothing is left: a comparison inside another one's operand
    is swapped in one round and the outer one in the next, on fresh tokens."""
    if path.endswith((".cpp", ".hpp")):
        return src, 0          # templates make < and > ambiguous
    swaps = 0
    while True:
        src, n = yoda_round(src, path, notes)
        if n == 0:
            return src, swaps
        swaps += n


def yoda_round(src, path, notes):
    """One round: every swap whose tokens no other swap of the round holds."""
    toks = tokenize(src)
    swaps = 0
    sig = sig_index(toks)
    s = 0
    edits = []
    while s < len(sig):
        t = toks[sig[s]]
        if t.kind == "op" and t.text in CMP:
            a = operand_left(toks, sig, s)
            b = operand_right(toks, sig, s)
            if a is not None and b is not None:
                lt = [toks[sig[k]].text for k in range(a, s)]
                lk = [toks[sig[k]].kind for k in range(a, s)]
                rt = [toks[sig[k]].text for k in range(s + 1, b + 1)]
                rk = [toks[sig[k]].kind for k in range(s + 1, b + 1)]
                if is_lvalue(lt, lk) and not is_lvalue(rt, rk):
                    first, last = sig[a], sig[b]
                    if toks[first].line != toks[last].line:
                        note = f"{path}:{t.line}: comparison over several lines, left as is"
                        if note not in notes:
                            notes.append(note)
                    else:
                        edits.append((a, s, b))
        s += 1
    # apply from the end so indices stay valid; a swap that holds tokens an
    # applied one already replaced waits for the next round
    applied_from = len(toks)
    for a, s, b in reversed(edits):
        first, opi, last = sig[a], sig[s], sig[b]
        if last >= applied_from:
            continue
        applied_from = first
        left = "".join(x.text for x in toks[first:opi]).rstrip()
        right_start = opi + 1
        lead = ""
        while toks[right_start].kind == "ws":
            lead += toks[right_start].text
            right_start += 1
        right = "".join(x.text for x in toks[right_start:last + 1])
        ws_before = "".join(x.text for x in toks[first:opi])[len(left):]
        new = f"{right}{ws_before}{CMP[toks[opi].text]}{lead}{left}"
        toks[first:last + 1] = [Tok("raw", new, toks[first].line)]
        swaps += 1
    return "".join(x.text for x in toks), swaps


# --------------------------------------------------------------------------
# Lint: what the two passes would change, plus what they never touch
# --------------------------------------------------------------------------

COMPARE = {"==", "!=", "<", ">", "<=", ">="}
NOTE_RE = re.compile(r"^.*?:(\d+): (.*)$")


def changed_lines(src, out):
    """The 1-based lines of src that a rewrite into out replaced, deleted or inserted after."""
    a, b = src.splitlines(), out.splitlines()
    lines = []
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            lines.extend(range(i1 + 1, i2 + 1))
        elif tag == "insert":
            lines.append(max(i1, 1))
    return lines


def compound_operands(toks):
    """Lines of if/while conditions whose && or || operands hold a bare comparison."""
    lines = []
    for i, t in enumerate(toks):
        if t.kind != "id" or t.text not in ("if", "while"):
            continue
        op = next_sig(toks, i)
        if op == -1 or toks[op].text != "(":
            continue
        cp = match_paren(toks, op)
        operands, cur, depth = [], [], 0
        for k in range(op + 1, cp):
            x = toks[k]
            if x.kind in ("ws", "nl", "cmt"):
                continue
            if x.kind == "op" and x.text in ("(", "["):
                depth += 1
            elif x.kind == "op" and x.text in (")", "]"):
                depth -= 1
            if depth == 0 and x.kind == "op" and x.text in ("&&", "||"):
                operands.append(cur)
                cur = []
                continue
            cur.append((x, depth))
        operands.append(cur)
        if len(operands) < 2:
            continue
        for opnd in operands:
            bare = any(x.kind == "op" and x.text in COMPARE and d == 0 for x, d in opnd)
            if bare:
                lines.append(t.line)
                break
    return lines


def lint_text(src, path):
    """(rule, line, message) for each E6, E7 and E8 violation in src."""
    found = set()
    for rule_id, fixer, what in (("E6", pass_blocks, "brace on its own line, ( cond ) spacing"),
                                 ("E7", pass_yoda, "constant or value on the left of the comparison")):
        notes = []
        out, _ = fixer(src, path, notes)
        for n in changed_lines(src, out):
            found.add((rule_id, n, what))
        for note in notes:
            m = NOTE_RE.match(note)
            if m:
                found.add((rule_id, int(m.group(1)), m.group(2) + "; fix it by hand"))
    toks = tokenize(src)
    for n in compound_operands(toks):
        found.add(("E6", n, "every comparison in a compound condition goes in parentheses"))
    for t in toks:
        if t.kind == "op" and t.text == "?":
            found.add(("E8", t.line, "ternary operator"))
    return sorted(found, key=lambda f: (f[1], f[0], f[2]))


def main(argv):
    mode, files = argv[1], argv[2:]
    if mode == "lint":
        bad = 0
        for path in files:
            with open(path, encoding="utf-8") as f:
                src = f.read()
            for rule_id, n, what in lint_text(src, path):
                print(f"{rule_id} {path}:{n} {what}")
                bad += 1
        sys.exit(1 if bad else 0)
    if mode == "check":
        with open(files[0]) as f:
            a = significant(tokenize(f.read()))
        with open(files[1]) as f:
            b = significant(tokenize(f.read()))
        sys.exit(0 if a == b else 1)
    notes, total = [], 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if mode == "blocks":
            out, n = pass_blocks(src, path, notes)
        else:
            out, n = pass_yoda(src, path, notes)
        if out != src:
            with open(path, "w", encoding="utf-8") as f:
                f.write(out)
        total += n
        print(f"{n:5d} {path}")
    print(f"total {total}")
    for n in notes:
        print("NOTE", n)


if __name__ == "__main__":
    main(sys.argv)
