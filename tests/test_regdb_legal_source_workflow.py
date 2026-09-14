from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RegdbLegalSourceWorkflowTests(unittest.TestCase):
    def test_admin_page_exposes_one_normal_update_action(self):
        source = (ROOT / "ui/regdb_page.py").read_text(encoding="utf-8")
        self.assertIn("최신본 업데이트", source)
        self.assertIn("refresh_all_legal_assets", source)
        self.assertIn("PDF·HWP/HWPX", source)
        self.assertIn("Excel 최신본", source)
        self.assertIn("고급 관리·감사정보", source)

        # Legacy per-appendix click choreography is no longer shown in normal UI.
        self.assertNotIn('button("공정안전보고서 별표 13 추출"', source)
        self.assertNotIn('button("화학사고예방관리계획서 별표 1 추출"', source)
        self.assertNotIn("승인 DB로 저장", source)
        self.assertNotIn("multiselect(", source)

    def test_admin_page_explains_single_click_updates_all_asset_layers(self):
        source = (ROOT / "ui/regdb_page.py").read_text(encoding="utf-8")
        self.assertIn("법제처 원본(PDF·HWP/HWPX), 판정용 규정 DB, 근거 PDF, Excel 최신본", source)
        self.assertIn("법령 개정 또는 공식 첨부원본 변경이 감지되었습니다", source)
        self.assertIn("자동검증을 통과하지 못한 법령·별표는 새 승인본으로 강제 적용하지 않고", source)

    def test_one_click_admin_action_clears_cached_diagnosis_state(self):
        source = (ROOT / "ui/regdb_page.py").read_text(encoding="utf-8")
        self.assertIn("st.cache_data.clear()", source)
        self.assertIn('st.page_link("ui/diagnosis_entry.py"', source)

    def test_diagnosis_hold_routes_user_to_admin_flow(self):
        source = (ROOT / "ui/diagnosis_entry.py").read_text(encoding="utf-8")
        self.assertIn("PDF·HWP/HWPX", source)
        self.assertIn("규정 DB 관리에서 확인하기", source)
        self.assertIn('st.page_link("ui/regdb_page.py"', source)
        self.assertIn("회사 Excel 입력 오류가 아니라 관리자 법령자료 준비상태", source)


if __name__ == "__main__":
    unittest.main()
