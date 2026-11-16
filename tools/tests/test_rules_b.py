"""Block B: the SDK pin, the board settings, the size and the RAM.

    tools/run_tests.sh
"""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import FIXTURES, ids, make_app, make_ctx

from kcheck import core

CMAKE = (FIXTURES / "good_app" / "CMakeLists.txt").read_text()
SDKCONFIG = (FIXTURES / "good_app" / "sdkconfig.defaults").read_text()
YML = (FIXTURES / "good_app" / "main" / "idf_component.yml").read_text()
BLOCK_B = {f"B{n}" for n in range(1, 10)}
CAMERA_GIT = "git@github.com:kodediy/kode-camera-sdk.git"
CAMERA = f"  kodediy/camera:\n    git: {CAMERA_GIT}\n    path: components/camera\n    version: v0.1.0\n"


def pin(kode, kui=None):
    out = YML.replace("components/kode\n    version: v00.00.27", f"components/kode\n    version: {kode}")
    if kui is not None:
        out = out.replace("components/kui\n    version: v00.00.27", f"components/kui\n    version: {kui}")
    return out


class RulesBTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def found(self, edits=None, level="reject", **ctx):
        app = make_app(self.tmp.name, edits)
        return ids(core.run(make_ctx(app, **ctx), only=BLOCK_B), level)

    def build_of(self, size):
        build = Path(self.tmp.name) / "build"
        build.mkdir()
        with open(build / "good_app.bin", "wb") as f:
            f.seek(size - 1)
            f.write(b"\0")
        (build / "good_app.elf").write_bytes(b"")
        return build

    def test_good_app_passes(self):
        self.assertEqual(self.found(), [])

    def test_b1_mixed_tags(self):
        self.assertEqual(self.found({"main/idf_component.yml": pin("v00.00.27", "v00.00.26")}), ["B1"])

    def test_b1_previous_release_passes(self):
        self.assertEqual(self.found({"main/idf_component.yml": pin("v00.00.26", "v00.00.26")}), [])

    def test_b1_too_old(self):
        self.assertEqual(self.found({"main/idf_component.yml": pin("v00.00.25", "v00.00.25")}), ["B1"])

    def test_b1_range(self):
        self.assertEqual(self.found({"main/idf_component.yml": pin('"^v00.00.27"', '"^v00.00.27"')}), ["B1"])

    def test_b1_quoted_ok(self):
        self.assertEqual(self.found({"main/idf_component.yml": pin('"v00.00.27"', '"v00.00.27"')}), [])

    def test_b1_order_is_by_version(self):
        self.assertEqual(self.found(releases=["v00.00.9", "v00.00.27", "v00.00.10"]), [])

    def test_b1_no_release_list(self):
        self.assertEqual(self.found(releases=[]), ["B1"])

    def test_b2_after_project(self):
        cmake = CMAKE.replace("set(IDF_TARGET esp32p4)\n", "") + "set(IDF_TARGET esp32p4)\n"
        self.assertEqual(self.found({"CMakeLists.txt": cmake}), ["B2"])

    def test_b3_extra_component_dirs(self):
        cmake = CMAKE.replace("project(good_app)", 'set(EXTRA_COMPONENT_DIRS "../sdk/components")\nproject(good_app)')
        self.assertEqual(self.found({"CMakeLists.txt": cmake}), ["B3"])

    def test_b3_sdk_submodule(self):
        self.assertEqual(self.found({".gitmodules": '[submodule "sdk"]\n\tpath = sdk\n\turl = x\n'}), ["B3"])

    def test_b3_wrong_partition_path(self):
        cfg = SDKCONFIG.replace("managed_components/kodediy__kbsp/partitions.csv", "../sdk/components/kbsp/partitions.csv")
        self.assertEqual(self.found({"sdkconfig.defaults": cfg}), ["B3"])

    def test_b4_role_os(self):
        cfg = SDKCONFIG.replace("CONFIG_KODEOS_BOOT_ROLE_APP=y", "CONFIG_KODEOS_BOOT_ROLE_OS=y")
        self.assertEqual(self.found({"sdkconfig.defaults": cfg}), ["B4"])

    def test_b5_copies_spiram(self):
        self.assertEqual(self.found({"sdkconfig.defaults": SDKCONFIG + "CONFIG_SPIRAM=y\n"}), ["B5"])

    def test_b5_bt_enabled_allowed(self):
        self.assertIn("CONFIG_BT_ENABLED=n", SDKCONFIG)
        self.assertEqual(self.found(), [])

    def test_b5_esp_hosted_enabled_allowed(self):
        self.assertIn("CONFIG_ESP_HOSTED_ENABLED=n", SDKCONFIG)
        self.assertEqual(self.found(), [])

    def test_b6_too_big(self):
        self.assertEqual(self.found(build=self.build_of(8388609)), ["B6"])

    def test_b6_at_the_cap_passes(self):
        self.assertEqual(self.found(build=self.build_of(8388608)), [])

    def test_b6_not_built(self):
        self.assertIn("B6", self.found(build=None))

    def test_b7_radio_off_alone(self):
        cfg = SDKCONFIG.replace("CONFIG_ESP_HOSTED_ENABLED=n\n", "")
        self.assertEqual(self.found({"sdkconfig.defaults": cfg}), ["B7"])

    def test_b7_mqtt_without_channel_off(self):
        main = (FIXTURES / "good_app" / "main" / "good_app_main.c").read_text()
        main = main.replace("    good_app_start();", '    good_app_start();\n    (void)kode_mqtt_pub("t", "m");')
        self.assertEqual(self.found({"main/good_app_main.c": main}), ["B7"])

    def test_b8_static_max_above_sdk(self):
        budget = "static_max 400000\ns_stack good_app_ao.c 8192\n"
        self.assertEqual(self.found({"ram_budget.txt": budget}), ["B8"])

    def test_b8_static_max_above_sdk_with_why(self):
        budget = "static_max 400000\nstatic_max_why two mesh stacks\ns_stack good_app_ao.c 8192\n"
        self.assertEqual(self.found({"ram_budget.txt": budget}), [])

    def test_b8_static_max_above_board(self):
        budget = "static_max 417001\nstatic_max_why two mesh stacks\ns_stack good_app_ao.c 8192\n"
        self.assertEqual(self.found({"ram_budget.txt": budget}), ["B8"])

    def test_b8_no_budget(self):
        self.assertEqual(self.found({"ram_budget.txt": None}), ["B8"])

    def test_b8_checker_fails(self):
        app = make_app(self.tmp.name)
        found = core.run(make_ctx(app, ram_checker=lambda e, b: (False, "foo_buf not listed")), only={"B8"})
        self.assertEqual(ids(found, "reject"), ["B8"])
        self.assertIn("foo_buf not listed", found[0].msg)

    def test_b1_foreign_git_url(self):
        yml = YML.replace("git@github.com:kodediy/kode-sdk.git", "git@github.com:evil/kode-sdk.git", 1)
        self.assertEqual(self.found({"main/idf_component.yml": yml}), ["B1"])

    def test_b1_wrong_component_path(self):
        self.assertEqual(self.found({"main/idf_component.yml": YML.replace("components/kui", "components/kode2")}), ["B1"])

    def test_b1_override_path(self):
        yml = YML.replace("    path: components/kui\n", "    path: components/kui\n    override_path: ../sdk/components/kui\n")
        self.assertEqual(self.found({"main/idf_component.yml": yml}), ["B1"])

    def test_b1_flow_style_explains_the_shape(self):
        yml = "dependencies:\n  kodediy/kode: {git: git@github.com:kodediy/kode-sdk.git, version: v00.00.27}\n"
        app = make_app(self.tmp.name, {"main/idf_component.yml": yml})
        found = [f for f in core.run(make_ctx(app), only={"B1"}) if f.level == "reject"]
        self.assertEqual(len(found), 1)
        self.assertIn("block form", found[0].msg)

    def test_b1_module_sdk_at_a_release(self):
        self.assertEqual(self.found({"main/idf_component.yml": YML + CAMERA},
                                    module_releases={CAMERA_GIT: ["v0.1.0"]}), [])

    def test_b1_module_sdk_without_a_release(self):
        found = core.run(make_ctx(make_app(self.tmp.name, {"main/idf_component.yml": YML + CAMERA})), only={"B1"})
        self.assertEqual(ids(found, "reject"), ["B1"])
        self.assertIn("published releases", found[0].msg)

    def test_b1_module_sdk_by_override_path(self):
        yml = YML + "  kodediy/camera:\n    override_path: ../kode-camera-sdk/components/camera\n"
        self.assertEqual(self.found({"main/idf_component.yml": yml}, module_releases={CAMERA_GIT: ["v0.1.0"]}),
                         ["B1"])

    def test_b1_module_sdk_mixed_tags(self):
        sys_dep = f"  kodediy/camera_sys:\n    git: {CAMERA_GIT}\n    path: components/camera_sys\n    version: v0.0.9\n"
        app = make_app(self.tmp.name, {"main/idf_component.yml": YML + CAMERA + sys_dep})
        found = core.run(make_ctx(app, module_releases={CAMERA_GIT: ["v0.1.0", "v0.0.9"]}), only={"B1"})
        self.assertEqual(ids(found, "reject"), ["B1"])
        self.assertIn("same tag", found[0].msg)

    def test_b1_unlisted_repository(self):
        yml = YML + CAMERA.replace("kode-camera-sdk", "kode-other-sdk")
        self.assertEqual(self.found({"main/idf_component.yml": yml},
                                    module_releases={CAMERA_GIT: ["v0.1.0"]}), ["B1"])

    def test_b5_extra_defaults_file(self):
        self.assertEqual(self.found({"sdkconfig.defaults.esp32p4": "CONFIG_SPIRAM=n\n"}), ["B5"])

    def test_b5_extra_defaults_in_cmake(self):
        cmake = CMAKE.replace('"${KBSP_BOARD};${CMAKE_CURRENT_LIST_DIR}/sdkconfig.defaults"',
                              '"${KBSP_BOARD};${CMAKE_CURRENT_LIST_DIR}/sdkconfig.defaults;${CMAKE_CURRENT_LIST_DIR}/more.defaults"')
        self.assertNotEqual(cmake, CMAKE)
        self.assertEqual(self.found({"CMakeLists.txt": cmake}), ["B5"])

    def test_b4_reads_the_resolved_sdkconfig_after_a_build(self):
        app = make_app(self.tmp.name, {"sdkconfig": "# CONFIG_KODEOS_BOOT_ROLE_APP is not set\nCONFIG_KODEOS_BOOT_ROLE_OS=y\n"})
        self.assertEqual(ids(core.run(make_ctx(app), only={"B4"}), "reject"), ["B4"])


if __name__ == "__main__":
    unittest.main()
