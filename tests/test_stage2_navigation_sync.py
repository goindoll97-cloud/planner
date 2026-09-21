from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage2NavigationSyncTests(unittest.TestCase):
    def test_navigation_does_not_depend_on_stored_projects(self) -> None:
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("list_projects", source)
        self.assertNotIn("stage2_validation_page.py", source)
        self.assertNotIn("stage2_review_page.py", source)



if __name__ == "__main__":
    unittest.main()
