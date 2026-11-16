"""The catalog-wide checks (A1, A2's catalog half) and the lists of changed and named apps.

    tools/run_tests.sh
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import TOOLS, ids

from kcheck import catalog
from kcheck.catalog import Change


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "categories.txt").write_text("# the list\ntools\ngames\n")

    def tearDown(self):
        self.tmp.cleanup()

    def modules(self, *entries):
        text = "".join(f'[submodule "{p}"]\n\tpath = {p}\n\turl = {u}\n' for p, u in entries)
        (self.root / ".gitmodules").write_text(text)

    def test_good_entry_passes(self):
        self.modules(("apps/scope", "../kode-app-scope.git"))
        self.assertEqual(catalog.check_catalog(self.root), [])

    def test_relative_url_required(self):
        self.modules(("apps/scope", "https://github.com/kodediy/kode-app-scope.git"))
        self.assertEqual(ids(catalog.check_catalog(self.root), "reject"), ["A1"])

    def test_url_must_name_kode_app_prefix(self):
        self.modules(("apps/scope", "../scope.git"))
        self.assertEqual(ids(catalog.check_catalog(self.root), "reject"), ["A1"])

    def test_path_outside_apps(self):
        self.modules(("scope", "../kode-app-scope.git"))
        self.assertIn("A1", ids(catalog.check_catalog(self.root), "reject"))

    def test_reserved_name(self):
        self.modules(("apps/kodeos", "../kode-app-kodeos.git"))
        self.assertEqual(ids(catalog.check_catalog(self.root), "reject"), ["A2"])

    def test_bad_name_chars(self):
        self.modules(("apps/Scope-2", "../kode-app-Scope-2.git"))
        self.assertEqual(ids(catalog.check_catalog(self.root), "reject"), ["A2"])

    def test_category_too_long(self):
        (self.root / "categories.txt").write_text("tools\nwaytoolongcategory\n")
        self.assertEqual(ids(catalog.check_catalog(self.root), "reject"), ["A3"])

    def test_category_duplicate(self):
        (self.root / "categories.txt").write_text("tools\ntools\n")
        self.assertEqual(ids(catalog.check_catalog(self.root), "reject"), ["A3"])

    def test_no_categories_file(self):
        (self.root / "categories.txt").unlink()
        self.assertEqual(ids(catalog.check_catalog(self.root), "reject"), ["A3"])

    def test_changed_apps_add_move_remove(self):
        repo = self.root / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "README.md")
        git(repo, "commit", "-q", "-m", "base")
        s1, s2 = "1" * 40, "2" * 40
        shas = [git(repo, "rev-parse", "HEAD").strip()]
        for sha in (s1, s2):
            git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},apps/x")
            git(repo, "commit", "-q", "-m", sha[:1])
            shas.append(git(repo, "rev-parse", "HEAD").strip())
        git(repo, "rm", "-q", "--cached", "apps/x")
        git(repo, "commit", "-q", "-m", "rm")
        shas.append(git(repo, "rev-parse", "HEAD").strip())
        self.assertEqual(catalog.changed_apps(repo, shas[0], shas[1]), [Change("x", None, s1)])
        self.assertEqual(catalog.changed_apps(repo, shas[1], shas[2]), [Change("x", s1, s2)])
        self.assertEqual(catalog.changed_apps(repo, shas[2], shas[3]), [Change("x", s2, None)])
        self.assertEqual(catalog.changed_apps(repo, shas[0], shas[0]), [])

    def test_changed_apps_branch_behind_main(self):
        repo = self.root / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "README.md")
        git(repo, "commit", "-q", "-m", "base")
        git(repo, "switch", "-q", "-c", "pr")
        git(repo, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},apps/x")
        git(repo, "commit", "-q", "-m", "add x")
        head = git(repo, "rev-parse", "HEAD").strip()
        git(repo, "switch", "-q", "main")
        git(repo, "update-index", "--add", "--cacheinfo", f"160000,{'2' * 40},apps/y")
        git(repo, "commit", "-q", "-m", "add y on main")
        base = git(repo, "rev-parse", "HEAD").strip()
        self.assertEqual(catalog.changed_apps(repo, base, head), [Change("x", None, "1" * 40)])

    def init_catalog(self):
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@t")
        git(self.root, "config", "user.name", "t")

    def test_plain_directory_under_apps_rejects(self):
        self.init_catalog()
        (self.root / "apps" / "x").mkdir(parents=True)
        (self.root / "apps" / "x" / "a.c").write_text("")
        git(self.root, "add", "apps/x/a.c")
        self.assertEqual(ids(catalog.check_catalog(self.root), "reject"), ["A1"])

    def test_gitlink_without_gitmodules_entry_rejects(self):
        self.init_catalog()
        git(self.root, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},apps/x")
        self.assertEqual(ids(catalog.check_catalog(self.root), "reject"), ["A1"])

    def test_gitlink_with_entry_passes(self):
        self.init_catalog()
        self.modules(("apps/x", "../kode-app-x.git"))
        git(self.root, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},apps/x")
        self.assertEqual(catalog.check_catalog(self.root), [])

    def commit_apps(self, **pins):
        """A catalog repository whose last commit pins each app to its sha."""
        self.init_catalog()
        self.modules(*((f"apps/{n}", f"../kode-app-{n}.git") for n in pins))
        for name, sha in pins.items():
            git(self.root, "update-index", "--add", "--cacheinfo", f"160000,{sha},apps/{name}")
        git(self.root, "add", ".gitmodules", "categories.txt")
        git(self.root, "commit", "-q", "-m", "apps")

    def test_named_apps_lists_each_pin_in_order(self):
        self.commit_apps(x="1" * 40, y="2" * 40)
        self.assertEqual(catalog.named_apps(self.root, ["y", "x"]),
                         [Change("y", None, "2" * 40), Change("x", None, "1" * 40)])

    def test_named_apps_refuses_what_is_not_an_app(self):
        self.commit_apps(x="1" * 40)
        (self.root / "apps").mkdir()
        (self.root / "apps" / "notes").write_text("x\n")
        git(self.root, "add", "apps/notes")
        git(self.root, "commit", "-q", "-m", "a file, not an app")
        for names in (["z"], ["x", "z"], ["x", "x"], ["../x"], ["notes"], ["X"]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                catalog.named_apps(self.root, names)

    def test_command_lists_named_apps_or_refuses(self):
        self.commit_apps(x="1" * 40)
        cmd = [sys.executable, "-I", str(TOOLS / "check_app.py"), "catalog", "--catalog", str(self.root), "--apps"]
        r = subprocess.run([*cmd, "x"], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, f"change x - {'1' * 40}\n"), r.stderr)
        r = subprocess.run([*cmd, "x", "z"], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("'z' is not an app of the catalog", r.stderr)


if __name__ == "__main__":
    unittest.main()
