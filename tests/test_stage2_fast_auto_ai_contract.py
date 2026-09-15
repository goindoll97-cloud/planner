from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage2FastAutoAIContractTests(unittest.TestCase):
    def test_stage5_runs_ai_only_when_user_enables_optional_toggle(self):
        source = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("st.toggle(", source)
        self.assertIn("AI로 문장 다듬은 초안도 만들기", source)
        self.assertIn("if use_ai:", source)
        self.assertIn("_render_ai_assistance(project)", source)
        self.assertIn("선택하지 않아도 아래에서 기본 초안을 바로", source)

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
