import pathlib
import unittest


ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]


class VisibleCopyTests(unittest.TestCase):
    def _source_files(self):
        return [
            ROOT_DIR / "0_Main.py",
            ROOT_DIR / "pages" / "1_PyLOAD_V3.0.py",
            ROOT_DIR / "pages" / "2_PyRUSH_V3.0.py",
            ROOT_DIR / "pages" / "3_PyLOG_V3.0.py",
            ROOT_DIR / "pages" / "4_PyLIVE_Test1.0.py",
            ROOT_DIR / "pages" / "5_PyCUT_BetaV1.0.py",
        ]

    def test_visible_ai_copy_uses_neutral_vendor_free_labels(self):
        visible_call_markers = (
            "st.markdown",
            "st.error",
            "st.warning",
            "_set_status",
            "log.append",
        )

        leaks = []
        for path in self._source_files():
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if "Gemini" not in line and "GEMINI" not in line:
                    continue
                if any(marker in line for marker in visible_call_markers):
                    leaks.append(f"{path.relative_to(ROOT_DIR)}:{line_no}: {line.strip()}")

        self.assertEqual(leaks, [])

    def test_visible_copy_has_no_known_typos(self):
        typo_checks = {
            "Dialouge": "Dialogue",
        }
        leaks = []
        for path in self._source_files():
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                for typo, correction in typo_checks.items():
                    if typo in line:
                        leaks.append(f"{path.relative_to(ROOT_DIR)}:{line_no}: use {correction}")

        self.assertEqual(leaks, [])

    def test_global_css_hides_streamlit_toolbar_chrome(self):
        utils_source = (ROOT_DIR / "utils.py").read_text(encoding="utf-8")

        self.assertIn('[data-testid="stToolbar"]', utils_source)
        self.assertIn('[data-testid="stDecoration"]', utils_source)
        self.assertIn("visibility:hidden!important", utils_source)


if __name__ == "__main__":
    unittest.main()
