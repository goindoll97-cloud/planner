from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage2FastAutoAIContractTests(unittest.TestCase):
    def test_stage5_does_not_run_ai_for_other_work_areas(self):
        source = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn('elif work_area == "AI 문장보강":', source)
        self.assertIn("_render_ai_status(project)", source)
        self.assertIn("AI를 기다리지 않고 바로", source)

    def test_auto_drafting_requests_only_missing_requirement_keys(self):
        source = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("requirement_keys=[spec.key for spec in missing]", source)

    def test_fast_mode_keeps_tiny_model_out_of_automatic_selection(self):
        source = (ROOT / "engine/stage2/local_ai_resilience.py").read_text(encoding="utf-8")
        self.assertIn("FAST_AUTO_MODEL_MIN_B = 4.0", source)
        self.assertIn("FAST_AUTO_MODEL_MAX_B = 8.5", source)
        self.assertIn("FAST_AUTO_BATCH_SIZE = 5", source)


if __name__ == "__main__":
    unittest.main()
