import json
import os
import tempfile
import unittest

import utils


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._old_config_file = utils.CONFIG_FILE
        self.addCleanup(self._restore_config_file)

    def _restore_config_file(self):
        utils.CONFIG_FILE = self._old_config_file

    def test_load_config_backs_up_corrupt_json_and_records_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            utils.CONFIG_FILE = os.path.join(tmp, "vmaster_config.json")
            with open(utils.CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write("{not valid json")

            self.assertEqual(utils.load_config(), {})

            backups = [
                name for name in os.listdir(tmp)
                if name.startswith("vmaster_config.json.corrupt-") and name.endswith(".bak")
            ]
            self.assertEqual(len(backups), 1)
            self.assertIn("vmaster_config.json", utils.get_last_config_error())

    def test_save_config_returns_false_without_clobbering_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            utils.CONFIG_FILE = os.path.join(tmp, "vmaster_config.json")
            with open(utils.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"keep": "me"}, f)

            ok = utils.save_config({"bad": {1, 2, 3}})

            self.assertFalse(ok)
            with open(utils.CONFIG_FILE, "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"keep": "me"})
            self.assertIn("vmaster_config.json", utils.get_last_config_error())


class StringSafetyTests(unittest.TestCase):
    def test_escape_html_escapes_text_for_unsafe_markdown(self):
        self.assertEqual(
            utils.escape_html('<script>alert("x")</script>'),
            '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;',
        )

    def test_js_literal_serializes_text_without_manual_escaping(self):
        self.assertEqual(
            utils.js_literal("เลือก 'quote'"),
            '"เลือก \'quote\'"',
        )

    def test_drive_query_values_escape_quotes_and_backslashes(self):
        self.assertEqual(
            utils.escape_drive_query_value("O'Brien\\clip"),
            "O\\'Brien\\\\clip",
        )

    def test_drive_name_contains_query_skips_empty_codes(self):
        query = utils.build_drive_name_contains_query([" ABC ", "", None, "O'Brien"])
        self.assertEqual(
            query,
            "(name contains 'ABC' or name contains 'O\\'Brien') and trashed = false",
        )

    def test_drive_name_equals_query_escapes_filename(self):
        query = utils.build_drive_name_equals_query("Bob's clip.mov")
        self.assertEqual(query, "name = 'Bob\\'s clip.mov' and trashed = false")

    def test_applescript_prompt_escapes_control_characters(self):
        escaped = utils.escape_applescript_string('เลือก "โฟลเดอร์" \\ ใหม่')
        self.assertEqual(escaped, 'เลือก \\"โฟลเดอร์\\" \\\\ ใหม่')


class ExistingUtilityBehaviorTests(unittest.TestCase):
    def test_extract_id_supports_common_google_url_shapes(self):
        self.assertEqual(
            utils.extract_id("https://docs.google.com/document/d/doc123/edit"),
            "doc123",
        )
        self.assertEqual(
            utils.extract_id("https://drive.google.com/open?id=file123"),
            "file123",
        )

    def test_sanitize_filename_replaces_unsafe_characters(self):
        self.assertEqual(utils.sanitize_filename('a/b:c * "x"'), "a_b_c____x_")

    def test_resolve_loadpap_page_maps_public_page_slugs(self):
        self.assertEqual(
            utils.resolve_loadpap_page("PyLOAD_V3.0"),
            "pages/1_PyLOAD_V3.0.py",
        )
        self.assertIsNone(utils.resolve_loadpap_page("missing"))

    def test_has_nonempty_text_rejects_blank_ui_values(self):
        self.assertFalse(utils.has_nonempty_text(""))
        self.assertFalse(utils.has_nonempty_text("  "))
        self.assertFalse(utils.has_nonempty_text(None))
        self.assertTrue(utils.has_nonempty_text("https://docs.google.com/spreadsheets/d/x"))


class TimecodeTests(unittest.TestCase):
    def test_parse_timecode_seconds_supports_loadpap_dot_notation(self):
        self.assertEqual(utils.parse_timecode_seconds("15.43"), 943.0)
        self.assertEqual(utils.parse_timecode_seconds("1.02.03"), 3723.0)

    def test_parse_timecode_seconds_supports_colon_notation_and_raw_seconds(self):
        self.assertEqual(utils.parse_timecode_seconds("01:02:03"), 3723.0)
        self.assertEqual(utils.parse_timecode_seconds("02:03"), 123.0)
        self.assertEqual(utils.parse_timecode_seconds("90"), 90.0)

    def test_parse_timecode_seconds_rejects_invalid_minutes_or_seconds(self):
        self.assertIsNone(utils.parse_timecode_seconds("1.99"))
        self.assertIsNone(utils.parse_timecode_seconds("1:60"))
        self.assertEqual(utils.parse_timecode_seconds("bad", default=0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
