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

    def test_intake_keeps_compact_role_based_missing_items_after_upload_controls(self):
        self.assertIn("### 아직 준비가 필요한 자료", self.source)
        self.assertIn("통합 Excel 보완 필요", self.source)
        self.assertIn("5단계에서 보고서 문장으로 정리할 항목", self.source)
        self.assertIn("담당자 별도 작성·첨부 예정", self.source)
        self.assertIn("기본자료 입력 완료 → 4. 작성자료 점검·보완", self.source)

    def test_legal_form_download_logic_is_not_loaded_on_intake_page(self):
        self.assertNotIn("official_form_bytes", self.source)
        self.assertNotIn("resolve_official_form_for_program", self.source)
        self.assertNotIn("LEGAL_FOCUS_KEY", self.source)

    def test_stage2_defers_external_msds_lookup_but_keeps_company_sds_upload(self):
        self.assertNotIn("KOSHA MSDS", self.source)
        self.assertNotIn("lookup_kosha_msds", self.source)
        self.assertNotIn("credential_status", self.source)
        self.assertNotIn("refresh_msds_references", self.source)
        self.assertIn("회사 보유 SDS/MSDS·도면·첨부자료", self.source)
        self.assertIn("SDS/MSDS", self.source)

    def test_upload_success_is_emitted_before_optional_refresh(self):
        """Workbook import must save and acknowledge before refreshing CAS controls."""
        marker = "통합 작성자료를 반영했습니다. 입력·확인"
        self.assertIn(marker, self.source)
        start = self.source.index(marker)
        rerun = self.source.find("st.rerun()", start)
        self.assertTrue(rerun == -1 or rerun > start)
        save = self.source.rfind("save_project(project)", 0, start)
        self.assertGreater(save, -1)
        self.assertLess(save, start)


if __name__ == "__main__":
    unittest.main()
