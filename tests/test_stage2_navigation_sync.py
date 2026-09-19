from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage2NavigationSyncTests(unittest.TestCase):
    def test_navigation_considers_all_stored_projects(self) -> None:
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("from engine.stage2.storage import list_projects, load_project", source)
        self.assertIn("for row in list_projects():", source)
        self.assertNotIn("stage2_validation_page.py", source)
        self.assertNotIn("stage2_review_page.py", source)

    def test_stage3_next_link_targets_registered_stage4_page(self) -> None:
        source = (ROOT / "ui" / "stage2_intake_page.py").read_text(encoding="utf-8")
        self.assertIn(
            'st.page_link("ui/stage2_validation_page.py", label="다음: 4. 작성자료 점검·보완"',
            source,
        )


if __name__ == "__main__":
    unittest.main()
