"""Block A: the app's identity, its metadata, its licence and its version.

    tools/run_tests.sh
"""
import subprocess
import sys
import tempfile
import unittest

from tests.helpers import FIXTURES, TOOLS, ids, make_app, make_ctx

from kcheck import core

CMAKE = (FIXTURES / "good_app" / "CMakeLists.txt").read_text()
MAIN = (FIXTURES / "good_app" / "main" / "good_app_main.c").read_text()
BLOCK_A = {"A2", "A3", "A4", "A5", "A6", "A7"}
STORE = (FIXTURES / "good_app" / "appdata" / "store.md").read_text()


def manifest(line):
    return MAIN.replace('KODE_APP_MANIFEST("Good App", "tools");', line)


def ver(v):
    return CMAKE.replace('set(PROJECT_VER "1.0.0")', f'set(PROJECT_VER "{v}")')


class RulesATest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def rejects(self, edits=None, name="good_app", **ctx):
        app = make_app(self.tmp.name, edits, name=name)
        return ids(core.run(make_ctx(app, **ctx), only=BLOCK_A), "reject")

    def test_good_app_passes(self):
        self.assertEqual(self.rejects(), [])

    def test_a2_project_not_folder(self):
        self.assertEqual(self.rejects({"CMakeLists.txt": CMAKE.replace("project(good_app)", "project(other)")}), ["A2"])

    def test_a2_bad_chars(self):
        self.assertEqual(self.rejects({"CMakeLists.txt": CMAKE.replace("project(good_app)", "project(Bad-App)")},
                                      name="Bad-App"), ["A2"])

    def test_a2_reserved(self):
        self.assertEqual(self.rejects({"CMakeLists.txt": CMAKE.replace("project(good_app)", "project(kodeos)")},
                                      name="kodeos"), ["A2"])

    def test_a2_no_cmakelists(self):
        self.assertIn("A2", self.rejects({"CMakeLists.txt": None}))

    def test_a3_missing(self):
        self.assertEqual(self.rejects({"main/good_app_main.c": manifest("")}), ["A3"])

    def test_a3_two_manifests(self):
        two = 'KODE_APP_MANIFEST("Good App", "tools");\nKODE_APP_MANIFEST("Again", "tools");'
        self.assertEqual(self.rejects({"main/good_app_main.c": manifest(two)}), ["A3"])

    def test_a3_in_a_comment_does_not_count(self):
        self.assertEqual(self.rejects({"main/good_app_main.c": manifest('/* KODE_APP_MANIFEST("X", "tools"); */')}),
                         ["A3"])

    def test_a3_display_32_chars(self):
        self.assertEqual(self.rejects({"main/good_app_main.c": manifest(f'KODE_APP_MANIFEST("{"x" * 32}", "tools");')}),
                         ["A3"])

    def test_a3_five_categories(self):
        line = 'KODE_APP_MANIFEST("Good App", "tools,games,tools,games,tools");'
        self.assertEqual(self.rejects({"main/good_app_main.c": manifest(line)}), ["A3"])

    def test_a3_unknown_category(self):
        self.assertEqual(self.rejects({"main/good_app_main.c": manifest('KODE_APP_MANIFEST("Good App", "toys");')}),
                         ["A3"])

    def test_a4_name_key(self):
        self.assertEqual(self.rejects({"appdata/app.json": '{"kode": "1", "name": "x"}'}), ["A4"])

    def test_a4_author_key(self):
        self.assertEqual(self.rejects({"appdata/app.json": '{"kode": "1", "author": "x"}'}), ["A4"])

    def test_a4_invalid_by_kappdata(self):
        self.assertEqual(self.rejects({"appdata/app.json": '{"kode": "1", "color": "blue"}'}), ["A4"])

    def test_a4_not_json(self):
        self.assertEqual(self.rejects({"appdata/app.json": '{"kode": '}), ["A4"])

    def test_a4_no_icon(self):
        self.assertEqual(self.rejects({"appdata/icon.png": None}), ["A4"])

    def test_a4_no_kappdata(self):
        self.assertEqual(self.rejects(kappdata_dir=None), ["A4"])

    def test_a5_mit_licence(self):
        self.assertEqual(self.rejects({"LICENSE": "MIT License\n\nPermission is hereby granted"}), ["A5"])

    def test_a5_missing(self):
        self.assertEqual(self.rejects({"LICENSE": None}), ["A5"])

    def test_a6_bad_format(self):
        self.assertEqual(self.rejects({"CMakeLists.txt": ver("1.0")}), ["A6"])

    def test_a6_missing(self):
        self.assertEqual(self.rejects({"CMakeLists.txt": CMAKE.replace('set(PROJECT_VER "1.0.0")', "")}), ["A6"])

    def test_a6_not_raised(self):
        self.assertEqual(self.rejects(old_cmake=ver("1.0.0")), ["A6"])

    def test_a6_lower_rejected(self):
        self.assertEqual(self.rejects(old_cmake=ver("1.0.10")), ["A6"])

    def test_a6_raised_passes(self):
        self.assertEqual(self.rejects(old_cmake=ver("0.9.9")), [])

    def test_a6_compares_numbers_not_text(self):
        self.assertEqual(self.rejects({"CMakeLists.txt": ver("1.0.10")}, old_cmake=ver("1.0.9")), [])

    def test_a6_new_app_passes(self):
        self.assertEqual(self.rejects(old_cmake=None), [])

    def test_a6_old_unreadable_passes(self):
        self.assertEqual(self.rejects(old_cmake="project(good_app)\n"), [])

    def test_cli_missing_cmake_exits_1(self):
        app = make_app(self.tmp.name, {"CMakeLists.txt": None})
        r = subprocess.run([sys.executable, "-I", str(TOOLS / "check_app.py"), "check", "--app", str(app),
                            "--catalog", str(FIXTURES / "catalog")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("A2 reject", r.stdout)

    def test_a5_truncated_gpl_rejects(self):
        gpl = (FIXTURES / "good_app" / "LICENSE").read_text()
        self.assertEqual(self.rejects({"LICENSE": gpl[: len(gpl) // 2]}), ["A5"])

    def test_a5_rewrapped_gpl_passes(self):
        gpl = (FIXTURES / "good_app" / "LICENSE").read_text()
        self.assertEqual(self.rejects({"LICENSE": " ".join(gpl.split())}), [])


    def levels(self, edits=None):
        found = core.run(make_ctx(make_app(self.tmp.name, edits)), only=BLOCK_A)
        return ids(found, "reject"), ids(found, "warn")

    def test_a7_good_text_passes(self):
        self.assertEqual(self.levels(), ([], []))

    def test_a7_missing_warns(self):
        self.assertEqual(self.levels({"appdata/store.md": None}), ([], ["A7"]))

    def test_a7_too_short_rejected(self):
        self.assertEqual(self.rejects({"appdata/store.md": "Reads cards."}), ["A7"])

    def test_a7_too_long_rejected(self):
        self.assertEqual(self.rejects({"appdata/store.md": "word " * 500}), ["A7"])

    def test_a7_heading_rejected(self):
        self.assertEqual(self.rejects({"appdata/store.md": "## How to use it\n" + STORE}), ["A7"])

    def test_a7_link_rejected(self):
        self.assertEqual(self.rejects({"appdata/store.md": STORE + "\n[docs](https://docs.kode.diy)"}), ["A7"])

    def test_a7_html_rejected(self):
        self.assertEqual(self.rejects({"appdata/store.md": STORE + "\n<br>"}), ["A7"])

    def test_a7_bold_and_lists_pass(self):
        self.assertEqual(self.rejects({"appdata/store.md": STORE + "\n- *one* more `item`"}), [])


if __name__ == "__main__":
    unittest.main()
