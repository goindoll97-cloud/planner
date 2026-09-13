from __future__ import annotations

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SimpleDiagnosisUIContractTests(unittest.TestCase):
    def test_company_facts_are_not_reentered_on_screen(self) -> None:
        text = (PROJECT_ROOT / "ui/diagnosis_page.py").read_text(encoding="utf-8")
        self.assertNotIn("st.radio(", text)
        self.assertNotIn("st.selectbox(", text)
        self.assertNotIn("st.multiselect(", text)
        self.assertNotIn("st.checkbox(", text)
        self.assertEqual(text.count("st.file_uploader("), 1)

    def test_followup_panel_is_not_rendered_after_main_page(self) -> None:
        text = (PROJECT_ROOT / "ui/diagnosis_entry.py").read_text(encoding="utf-8")
        self.assertNotIn("render_psm_followup_panel", text)
        self.assertIn("유일한 사실 입력원본", text)

    def test_incomplete_workbook_is_presented_as_requests_only(self) -> None:
        text = (PROJECT_ROOT / "ui/diagnosis_page.py").read_text(encoding="utf-8")
        self.assertIn("## 요청사항", text)
        self.assertIn("화면에서 별도로 선택할 항목은 없습니다", text)
        self.assertIn("st.stop()", text)

    def test_completed_diagnosis_links_to_registered_scope_page(self) -> None:
        diagnosis = (PROJECT_ROOT / "ui/diagnosis_page.py").read_text(encoding="utf-8")
        app = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('st.page_link("ui/stage2_scope_page.py"', diagnosis)
        self.assertIn('st.Page("ui/stage2_scope_page.py"', app)
        self.assertNotIn("stage2_project_page.py", diagnosis)


if __name__ == "__main__":
    unittest.main()
