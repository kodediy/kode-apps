"""The marketplace listing read from an app, and the category map against categories.txt.

    tools/run_tests.sh
"""
import tempfile
import unittest

from tests.helpers import FIXTURES, KODEOS_TOOLS, TOOLS, make_app

from kcheck import catalog, listing

MAIN = (FIXTURES / "good_app" / "main" / "good_app_main.c").read_text()


class ListingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, edits=None, name="good_app"):
        return listing.listing(make_app(self.tmp.name, edits, name=name), KODEOS_TOOLS)

    def test_good_app(self):
        got = self.read()
        self.assertEqual(got["slug"], "good-app")
        self.assertEqual(got["name"], "Good App")
        self.assertEqual(got["version"], "1.0.0")
        self.assertEqual(got["category"], "tool")
        self.assertEqual(got["description"], "A fixture.")
        self.assertEqual(got["githubUrl"], "https://github.com/kodediy/kode-app-good_app")
        self.assertEqual(got["icon"].name, "icon.png")
        self.assertEqual(got["color"], "#8E8E93")

    def test_no_color_lays_the_cover_on_black(self):
        got = self.read({"appdata/app.json": '{"kode": "1", "description": "A fixture."}'})
        self.assertEqual(got["color"], listing.COVER_GROUND)

    def test_every_category_is_the_marketplaces(self):
        for cat, theirs in listing.CATEGORY_MAP.items():
            self.assertIn(theirs, listing.MARKETPLACE_CATEGORIES, cat)

    def test_first_category_decides(self):
        main = MAIN.replace('"tools");', '"games,tools");')
        self.assertEqual(self.read({"main/good_app_main.c": main})["category"], "game")

    def test_unmapped_category_refused(self):
        main = MAIN.replace('"tools");', '"robots");')
        with self.assertRaises(ValueError):
            self.read({"main/good_app_main.c": main})

    def test_no_manifest_refused(self):
        main = MAIN.replace('KODE_APP_MANIFEST("Good App", "tools");', "")
        with self.assertRaises(ValueError):
            self.read({"main/good_app_main.c": main})

    def test_no_icon_refused(self):
        with self.assertRaises(ValueError):
            self.read({"appdata/icon.png": None})

    def test_slug_turns_underscores_into_hyphens(self):
        self.assertEqual(listing.slug("kody_kart2"), "kody-kart2")

    def test_every_catalog_category_is_mapped(self):
        for root in (TOOLS.parent, FIXTURES / "catalog"):
            for _, cat in catalog.categories(root):
                self.assertIn(cat, listing.CATEGORY_MAP, f"{root / 'categories.txt'}: {cat}")


if __name__ == "__main__":
    unittest.main()
