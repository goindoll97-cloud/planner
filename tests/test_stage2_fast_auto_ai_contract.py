from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage2FastAutoAIContractTests(unittest.TestCase):
    def test_stage5_ai_is_optional_and_starts_only_after_explicit_action(self):
        source = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("st.toggle(", source)
        self.assertIn("AI로 문장 다듬은 초안 만들기", source)
        self.assertIn("if use_ai:", source)
        self.assertIn("_render_ai_assistance(project)", source)
        self.assertIn("AI 문장 다듬기 시작", source)
        self.assertIn("선택하지 않아도 위에서 기본 초안을 바로", source)

    def test_auto_drafting_requests_only_pending_missing_narrative_keys(self):
        source = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("def _automatic_ai_candidates", source)
        self.assertIn("CONFIRMED_STATUSES", source)
        self.assertIn("if not has_confirmed_narrative", source)
        self.assertIn("requirement_keys=[spec.key for spec in batch]", source)
        self.assertIn("AI_UI_BATCH_SIZE = 3", source)

    def test_stage5_shows_progress_during_ai_work(self):
        source = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("st.progress(0.0", source)
        self.assertIn("progress.progress", source)
        self.assertIn("AI로 정리할 설명문: {pending_total}개", source)

    def test_fast_mode_keeps_tiny_model_out_of_automatic_selection(self):
        source = (ROOT / "engine/stage2/local_ai_resilience.py").read_text(encoding="utf-8")
        self.assertIn("FAST_AUTO_MODEL_MIN_B = 4.0", source)
        self.assertIn("FAST_AUTO_MODEL_MAX_B = 8.5", source)
        self.assertIn("FAST_AUTO_BATCH_SIZE = 5", source)


if __name__ == "__main__":
    unittest.main()
