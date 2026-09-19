from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Stage2NavigationLinkTests(unittest.TestCase):
    def test_legacy_stage_3_to_5_are_not_registered_and_scope_page_points_to_the_new_psm_page(self):
        app_text = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        scope_text = (PROJECT_ROOT / "ui/stage2_scope_page.py").read_text(encoding="utf-8")

        for legacy in ("stage2_intake_page.py", "stage2_validation_page.py", "stage2_review_page.py"):
            self.assertNotIn(legacy, app_text)
        self.assertIn('st.Page("ui/psm_workspace_page.py"', app_text)
        self.assertIn('st.page_link("ui/psm_workspace_page.py"', scope_text)
        self.assertNotIn("stage2_intake_page.py", scope_text)


if __name__ == "__main__":
    unittest.main()
