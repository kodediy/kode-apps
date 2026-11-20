"""publish_app.py against a scripted marketplace: what it sends, in which order, and when it stops.

    tools/run_tests.sh
"""
import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from tests.helpers import KODEOS_TOOLS, TOOLS, make_app, png_bytes

from kcheck import cover, listing

spec = importlib.util.spec_from_file_location("publish_app", TOOLS / "publish_app.py")
publish_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish_app)


class FakeApi:
    """Answers each (method, path) from a script, in order, and records what was asked."""

    def __init__(self, script):
        self.script = {key: list(answers) for key, answers in script.items()}
        self.calls = []

    def call(self, method, path, body=None, content_type=None):
        self.calls.append((method, path, body))
        return self.script[(method, path)].pop(0)


MINE_EMPTY = (200, {"apps": []})
COVER = (201, {"url": "https://cdn.example/cover.png"})
SHOT = (201, {"url": "https://cdn.example/shot1.png"})
UPLOADED = (201, {"id": "a1", "created": True, "submission": {"id": "s1", "status": "pending"}})


def mine_with(version, state="published"):
    return (200, {"apps": [{"id": "a1", "slug": "good-app", "version": version, "reviewState": state}]})


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app = make_app(self.tmp.name)
        self.info = listing.listing(app, KODEOS_TOOLS)
        self.bin = Path(self.tmp.name) / "good_app.bin"
        self.bin.write_bytes(b"\xe9" + b"\0" * 63)

    def tearDown(self):
        self.tmp.cleanup()

    def run_with(self, script):
        api = FakeApi(script)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = publish_app.publish(api, self.info, self.bin)
        return code, [(m, p) for m, p, _ in api.calls], api.calls

    def test_first_publish_uploads_cover_then_app(self):
        code, calls, raw = self.run_with({("GET", "/apps/mine"): [MINE_EMPTY],
                                          ("POST", "/apps/upload-cover"): [COVER],
                                          ("POST", "/apps/upload-screenshot"): [SHOT],
                                          ("POST", "/apps/upload"): [UPLOADED]})
        self.assertEqual(code, 0)
        self.assertEqual(calls, [("GET", "/apps/mine"), ("POST", "/apps/upload-cover"),
                                 ("POST", "/apps/upload-screenshot"), ("POST", "/apps/upload")])
        body = raw[3][2]
        for field in (b'name="slug"\r\n\r\ngood-app', b'name="status"\r\n\r\npublished',
                      b'name="coverImageUrl"\r\n\r\nhttps://cdn.example/cover.png', b'name="version"\r\n\r\n1.0.0',
                      b'name="screenshots"\r\n\r\n["https://cdn.example/shot1.png"]',
                      b'name="description"\r\n\r\nA fixture that stands for an app of the catalog.'):
            self.assertIn(field, body)

    def test_transparent_icon_goes_up_opaque(self):
        icon = png_bytes(6, [bytes([0, 0, 0, 0])])
        self.info = listing.listing(make_app(self.tmp.name, {"appdata/icon.png": icon}, name="clear_app"),
                                    KODEOS_TOOLS)
        code, _, raw = self.run_with({("GET", "/apps/mine"): [MINE_EMPTY],
                                      ("POST", "/apps/upload-cover"): [COVER],
                                          ("POST", "/apps/upload-screenshot"): [SHOT],
                                      ("POST", "/apps/upload"): [UPLOADED]})
        self.assertEqual(code, 0)
        self.assertIn(cover.opaque(icon, "#8E8E93"), raw[1][2])
        self.assertNotIn(icon, raw[1][2])

    def test_same_version_sends_nothing(self):
        code, calls, _ = self.run_with({("GET", "/apps/mine"): [mine_with("1.0.0")]})
        self.assertEqual((code, calls), (0, [("GET", "/apps/mine")]))

    def test_newer_version_there_sends_nothing(self):
        code, calls, _ = self.run_with({("GET", "/apps/mine"): [mine_with("1.2.0")]})
        self.assertEqual((code, calls), (0, [("GET", "/apps/mine")]))

    def test_older_version_is_replaced(self):
        code, calls, _ = self.run_with({("GET", "/apps/mine"): [mine_with("0.9.0")],
                                        ("POST", "/apps/upload-cover"): [COVER],
                                          ("POST", "/apps/upload-screenshot"): [SHOT],
                                        ("POST", "/apps/upload"): [(200, {"id": "a1", "created": False})]})
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], ("POST", "/apps/upload"))

    def test_pending_submission_is_withdrawn_once(self):
        code, calls, _ = self.run_with({("GET", "/apps/mine"): [mine_with("0.9.0", "published_update_in_review")],
                                        ("POST", "/apps/upload-cover"): [COVER],
                                          ("POST", "/apps/upload-screenshot"): [SHOT],
                                        ("POST", "/apps/upload"): [(409, {"error": "in_review"}), UPLOADED],
                                        ("DELETE", "/apps/a1/submit"): [(200, {})]})
        self.assertEqual(code, 0)
        self.assertEqual(calls[-2:], [("DELETE", "/apps/a1/submit"), ("POST", "/apps/upload")])

    def test_draft_without_submission_fails(self):
        code, _, _ = self.run_with({("GET", "/apps/mine"): [MINE_EMPTY],
                                    ("POST", "/apps/upload-cover"): [COVER],
                                          ("POST", "/apps/upload-screenshot"): [SHOT],
                                    ("POST", "/apps/upload"): [(201, {"id": "a1", "submitError": "no_cover"})]})
        self.assertEqual(code, 1)

    def test_refused_upload_fails(self):
        code, _, _ = self.run_with({("GET", "/apps/mine"): [MINE_EMPTY],
                                    ("POST", "/apps/upload-cover"): [COVER],
                                          ("POST", "/apps/upload-screenshot"): [SHOT],
                                    ("POST", "/apps/upload"): [(400, {"error": "file too large"})]})
        self.assertEqual(code, 1)

    def test_acting_as_a_publisher_is_on_every_url(self):
        self.assertEqual(publish_app.Api("https://api.example/", "t", "kode").url("/apps/mine"),
                         "https://api.example/apps/mine?as=kode")
        self.assertEqual(publish_app.Api("https://api.example", "t").url("/apps/mine"),
                         "https://api.example/apps/mine")

    def test_no_cover_url_stops_before_the_upload(self):
        code, calls, _ = self.run_with({("GET", "/apps/mine"): [MINE_EMPTY],
                                        ("POST", "/apps/upload-cover"): [(500, {})]})
        self.assertEqual(code, 1)
        self.assertNotIn(("POST", "/apps/upload"), calls)


    def test_refused_screenshot_stops_before_the_upload(self):
        code, calls, _ = self.run_with({("GET", "/apps/mine"): [MINE_EMPTY],
                                        ("POST", "/apps/upload-cover"): [COVER],
                                        ("POST", "/apps/upload-screenshot"): [(400, {"error": "screenshot_too_small"})]})
        self.assertEqual(code, 1)
        self.assertNotIn(("POST", "/apps/upload"), calls)

    def test_no_screenshots_sends_no_field(self):
        self.info = dict(self.info, screenshots=[])
        code, calls, raw = self.run_with({("GET", "/apps/mine"): [MINE_EMPTY],
                                          ("POST", "/apps/upload-cover"): [COVER],
                                          ("POST", "/apps/upload"): [UPLOADED]})
        self.assertEqual(code, 0)
        self.assertNotIn(("POST", "/apps/upload-screenshot"), calls)
        self.assertNotIn(b'name="screenshots"', raw[-1][2])


if __name__ == "__main__":
    unittest.main()
