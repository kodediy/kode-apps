"""The style tools: cstyle.py's lint mode, its fix modes, and basic_types.py's findings.

    tools/run_tests.sh
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

from tests.helpers import FIXTURES, TOOLS

import basic_types
import cstyle


def lint(src):
    return [(rule, line) for rule, line, _ in cstyle.lint_text(src, "x.c")]


class CstyleLintTest(unittest.TestCase):
    def test_brace_same_line(self):
        self.assertIn(("E6", 1), lint("if ( x ) {\n}\n"))

    def test_spacing(self):
        self.assertEqual(lint("if (x)\n{\n}\n"), [("E6", 1)])

    def test_compound_operand_needs_parens(self):
        self.assertEqual(lint("if ( (0 < n) && 'a' == p )\n{\n}\n"), [("E6", 1)])

    def test_compound_bare_flag_is_fine(self):
        self.assertEqual(lint("if ( (0U < n) && !own )\n{\n}\n"), [])

    def test_yoda(self):
        self.assertEqual(lint("if ( p == NULL )\n{\n}\n"), [("E7", 1)])

    def test_ternary(self):
        self.assertEqual(lint("a = b ? c : d;\n"), [("E8", 1)])

    def test_question_mark_in_string_is_fine(self):
        self.assertEqual(lint('s = "why?";\n'), [])

    def test_one_line_block_reported(self):
        self.assertIn(("E6", 1), lint("while ( 0 < n ) { --n; }\n"))

    def test_clean_file_silent(self):
        src = (FIXTURES / "good_app" / "main" / "good_app_ao.c").read_text()
        self.assertEqual(cstyle.lint_text(src, "good_app_ao.c"), [])

    def test_lint_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.c"
            bad.write_text("if (x) {\n}\n")
            r = subprocess.run([sys.executable, "-I", str(TOOLS / "cstyle.py"), "lint", str(bad)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertTrue(r.stdout.startswith(f"E6 {bad}:1 "), r.stdout)
            good = FIXTURES / "good_app" / "main" / "good_app_ao.c"
            r = subprocess.run([sys.executable, "-I", str(TOOLS / "cstyle.py"), "lint", str(good)],
                               capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stdout), (0, ""))


class CstyleFixModesTest(unittest.TestCase):
    def test_blocks_mode_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.c"
            shutil.copy(FIXTURES / "cstyle" / "before.c", p)
            for mode in ("blocks", "yoda"):
                subprocess.run([sys.executable, "-I", str(TOOLS / "cstyle.py"), mode, str(p)],
                               check=True, capture_output=True)
            self.assertEqual(p.read_text(), (FIXTURES / "cstyle" / "after.c").read_text())

    def test_every_mode_closes_its_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.c"
            shutil.copy(FIXTURES / "cstyle" / "before.c", p)
            for args in (["lint", p], ["check", p, p], ["blocks", p], ["yoda", p]):
                r = subprocess.run([sys.executable, "-I", "-W", "always::ResourceWarning",
                                    str(TOOLS / "cstyle.py"), *map(str, args)],
                                   capture_output=True, text=True)
                self.assertNotIn("ResourceWarning", r.stderr, args[0])


class BasicTypesTest(unittest.TestCase):
    def test_scan_and_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.c"
            p.write_text("int n;\nuint8_t k;\n")
            self.assertEqual(basic_types.scan([tmp]), {str(p): [(1, "int n;")]})
            r = subprocess.run([sys.executable, "-I", str(TOOLS / "basic_types.py"), "--findings", tmp],
                               capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), f"E9 {p}:1 int n;")

    def test_scan_closes_each_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.c").write_text("int n;\n")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                basic_types.scan([tmp])
            self.assertEqual([w for w in caught if w.category is ResourceWarning], [])


if __name__ == "__main__":
    unittest.main()
