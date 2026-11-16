"""Block C: what an app does at run time.

    tools/run_tests.sh
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import FIXTURES, ids, make_app, make_ctx

from kcheck import core

AO = (FIXTURES / "good_app" / "main" / "good_app_ao.c").read_text()
SDKCONFIG = (FIXTURES / "good_app" / "sdkconfig.defaults").read_text()
BLOCK_C = {f"C{n}" for n in range(1, 13)}


def in_idle(line):
    """The fixture AO with line added inside its state handler."""
    return AO.replace('        KLOG_I(TAG, "a button");', f'        KLOG_I(TAG, "a button");\n        {line}')


def plain_file(body):
    return ('/* SPDX-License-Identifier: GPL-3.0-or-later */\n/**\n * @file task.c\n * @brief A task.\n */\n'
            f'#include "kode.h"\n\nvoid task(void)\n{{\n    {body}\n}}\n')


class RulesCTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def found(self, edits=None, level=None, **ctx):
        app = make_app(self.tmp.name, edits)
        return [(f.rule, f.level) for f in core.run(make_ctx(app, **ctx), only=BLOCK_C)
                if level is None or f.level == level]

    def test_good_app_silent(self):
        self.assertEqual(self.found(), [])

    def test_c2_delay_in_ao_warns(self):
        self.assertEqual(self.found({"main/good_app_ao.c": in_idle("kode_delay(10U);")}), [("C2", "warn")])

    def test_c2_delay_in_plain_task_silent(self):
        self.assertEqual(self.found({"main/task.c": plain_file("kode_delay(10U);")}), [])

    def test_c2_resolve_in_ao_warns(self):
        self.assertEqual(self.found({"main/good_app_ao.c": in_idle("kode_net_resolve(name, &addr);")}),
                         [("C2", "warn")])

    def test_c2_rfid_read_in_ao_warns(self):
        self.assertEqual(self.found({"main/good_app_ao.c": in_idle("kode_rfid_read_id(1000U);")}), [("C2", "warn")])

    def test_c2_nfc_read_id_in_ao_warns(self):
        self.assertEqual(self.found({"main/good_app_ao.c": in_idle("kode_nfc_read_id(1000U);")}), [("C2", "warn")])

    def test_c2_sem_wait_in_ao_warns(self):
        self.assertEqual(self.found({"main/good_app_ao.c": in_idle("(void)khal_sem_wait_timeout(sem, 10U);")}),
                         [("C2", "warn")])

    def test_c2_watch_off_rejects(self):
        self.assertEqual(self.found({"sdkconfig.defaults": SDKCONFIG + "CONFIG_KQP_AO_WATCH=n\n"}), [("C2", "reject")])

    def test_c3_i2s_include_warns(self):
        ao = AO.replace('#include "kode_log.h"', '#include "kode_log.h"\n#include "driver/i2s_std.h"')
        self.assertEqual(self.found({"main/good_app_ao.c": ao}), [("C3", "warn")])

    def test_c5_publish_own_signal_warns(self):
        ao = AO.replace("/** @brief The Active Object. */",
                        "/** @brief The app's own signals. */\nenum { GOOD_TICK_SIG = MAX_SIG };\n\n"
                        "/** @brief The Active Object. */")
        ao = ao.replace('        KLOG_I(TAG, "a button");',
                        '        KLOG_I(TAG, "a button");\n        QACTIVE_PUBLISH(Q_NEW(QEvt, GOOD_TICK_SIG), &me->super);')
        self.assertEqual(self.found({"main/good_app_ao.c": ao}), [("C5", "warn")])

    def test_c5_post_own_signal_silent(self):
        ao = AO.replace("/** @brief The Active Object. */",
                        "enum { GOOD_TICK_SIG = MAX_SIG };\n\n/** @brief The Active Object. */")
        ao = ao.replace('        KLOG_I(TAG, "a button");',
                        '        KLOG_I(TAG, "a button");\n        QACTIVE_POST(&me->super, Q_NEW(QEvt, GOOD_TICK_SIG), me);')
        self.assertEqual(self.found({"main/good_app_ao.c": ao}), [])

    def test_c7_missing_task_name(self):
        ao = AO.replace('    QActive_setAttr(&s_good.super, TASK_NAME_ATTR, "good_app");\n', "")
        self.assertEqual(self.found({"main/good_app_ao.c": ao}), [("C7", "reject")])

    def test_c7_name_set_after_start(self):
        ao = AO.replace('    QActive_setAttr(&s_good.super, TASK_NAME_ATTR, "good_app");\n', "")
        ao = ao.replace("(void *)0);\n}", '(void *)0);\n    QActive_setAttr(&s_good.super, TASK_NAME_ATTR, "x");\n}')
        self.assertEqual(self.found({"main/good_app_ao.c": ao}), [("C7", "reject")])

    def test_c8_small_stack_macro_warns(self):
        body = '#define W_STACK 4096U\nvoid w(void)\n{\n    (void)kode_worker_start(&s_w, &s_ao, "w", W_STACK, 2U, 4U);\n}\n'
        self.assertEqual(self.found({"main/task.c": plain_file("") + body}), [("C8", "warn")])

    def test_c8_big_literal_silent(self):
        self.assertEqual(self.found({"main/task.c": plain_file('(void)kode_worker_start(&s_w, &s_ao, "w", 8192U, 2U, 4U);')}),
                         [])

    def test_c11_report_rejects(self):
        report = Path(self.tmp.name) / "gitleaks.json"
        report.write_text(json.dumps([{"File": "main/wifi.c", "StartLine": 7, "RuleID": "generic-api-key",
                                       "Commit": "0123456789abcdef"}]))
        found = core.run(make_ctx(make_app(self.tmp.name), secrets_report=report), only={"C11"})
        self.assertEqual([(f.rule, f.level, f.path, f.line) for f in found], [("C11", "reject", "main/wifi.c", 7)])
        self.assertIn("0123456789ab", found[0].msg)

    def test_c11_empty_report_passes(self):
        report = Path(self.tmp.name) / "gitleaks.json"
        report.write_text("[]")
        self.assertEqual(self.found(secrets_report=report), [])

    def test_c11_missing_report_rejects(self):
        self.assertEqual(self.found(secrets_report=Path(self.tmp.name) / "none.json"), [("C11", "reject")])

    def test_c11_ignore_file_warns(self):
        self.assertEqual(self.found({".gitleaksignore": "0123abcd:main/wifi.c:generic-api-key:7\n"}), [("C11", "warn")])

    def test_c12_ota_call(self):
        self.assertEqual(self.found({"main/task.c": plain_file("(void)esp_ota_set_boot_partition(p);")}),
                         [("C12", "reject")])

    def test_c12_partition_write(self):
        self.assertEqual(self.found({"main/task.c": plain_file("(void)esp_partition_erase_range(p, 0U, 4096U);")}),
                         [("C12", "reject")])

    def test_c12_in_comment_silent(self):
        self.assertEqual(self.found({"main/task.c": plain_file("/* esp_ota_begin() is not for apps */")}), [])

    def test_c11_gitleaks_config_in_app_rejects(self):
        self.assertEqual(self.found({".gitleaks.toml": "[allowlist]\npaths = ['.*']\n"}), [("C11", "reject")])

    def test_c11_inline_allow_rejects(self):
        self.assertEqual(self.found({"main/task.c": plain_file('const char *k = "x"; /* gitleaks:allow */')}),
                         [("C11", "reject")])

    def test_c11_not_scanned_warns(self):
        self.assertEqual(self.found(secrets_report=None), [("C11", "warn")])

    def test_c12_flash_write(self):
        self.assertEqual(self.found({"main/task.c": plain_file("(void)esp_flash_write(f, b, 0U, 4U);")}),
                         [("C12", "reject")])

    def test_c12_spi_flash_erase(self):
        self.assertEqual(self.found({"main/task.c": plain_file("(void)spi_flash_erase_range(0U, 4096U);")}),
                         [("C12", "reject")])


if __name__ == "__main__":
    unittest.main()
