from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Stage2NavigationLinkTests(unittest.TestCase):
    def test_validation_page_links_to_registered_review_page(self):
        app_text = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        validation_text = (PROJECT_ROOT / "ui/stage2_validation_page.py").read_text(encoding="utf-8")

        self.assertIn('st.Page("ui/stage2_review_page.py", title="5. 작성·검토"', app_text)
        self.assertIn('st.page_link("ui/stage2_review_page.py", label="5. 작성·검토로 이동"', validation_text)
        self.assertNotIn("ui/stage2_project_page.py", validation_text)


if __name__ == "__main__":
    unittest.main()
