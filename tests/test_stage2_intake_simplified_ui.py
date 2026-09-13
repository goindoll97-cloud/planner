from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INTAKE_PAGE = ROOT / "ui" / "stage2_intake_page.py"


class Stage2IntakeSimplifiedUITests(unittest.TestCase):
    def setUp(self):
        self.source = INTAKE_PAGE.read_text(encoding="utf-8")

    def test_large_status_dashboard_and_why_needed_sections_are_removed(self):
        self.assertNotIn("### 4. 해야 할 일·작성상태 확인", self.source)
        self.assertNotIn("왜 필요한가?", self.source)
        self.assertNotIn("법적 의무 근거", self.source)
        self.assertNotIn("세부 작성기준", self.source)
        self.assertNotIn("법령·근거 라이브러리에서 이 항목 자세히 보기", self.source)

    def test_intake_keeps_only_compact_missing_items_after_upload_controls(self):
        self.assertIn("### 추가로 필요한 항목", self.source)
        self.assertIn("추가 작성·업로드 필요", self.source)
        self.assertIn("통합 Excel에 추가 작성", self.source)
        self.assertIn("파일 추가 업로드", self.source)
        self.assertIn("사람 확인", self.source)
        self.assertIn("다음: 작성자료 교차검증", self.source)

    def test_legal_form_download_logic_is_not_loaded_on_intake_page(self):
        self.assertNotIn("official_form_bytes", self.source)
        self.assertNotIn("resolve_official_form_for_program", self.source)
        self.assertNotIn("LEGAL_FOCUS_KEY", self.source)

    def test_upload_success_is_not_immediately_hidden_by_rerun(self):
        self.assertNotIn("st.rerun()", self.source)


if __name__ == "__main__":
    unittest.main()
