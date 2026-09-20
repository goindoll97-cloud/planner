from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2 import psm_narrative_workspace as nw


class RejectionReasonTests(unittest.TestCase):
    def test_borrowed_fact_and_number_reasons_are_plain_and_do_not_blame_missing_facts(self):
        borrowed = nw.rejection_reason(("다른 항목의 사실을 가져다 썼습니다: cap.facts.community",))
        self.assertIn("다시 만들면", borrowed)
        self.assertNotIn("cap.facts", borrowed)
        number = nw.rejection_reason(("확인자료에 없는 수치: 800kg",))
        self.assertIn("800kg", number)
        self.assertNotIn("사실을 더 적고", number)

    def test_unknown_warnings_are_still_shown(self):
        self.assertIn("알 수 없는 경고", nw.rejection_reason(("알 수 없는 경고",)))

    def test_panel_keeps_the_reasons_across_the_rerun(self):
        text = (Path(__file__).resolve().parents[1] / "ui/narrative_panel.py").read_text(encoding="utf-8")
        self.assertIn('st.session_state[f"{prefix}_rejected"]', text)
        self.assertNotIn("사실을 더 적고 다시 시도하세요", text)


if __name__ == "__main__":
    unittest.main()
