from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RegdbLegalSourceWorkflowTests(unittest.TestCase):
    def test_admin_page_starts_with_all_official_attachment_formats(self):
        source = (ROOT / "ui/regdb_page.py").read_text(encoding="utf-8")
        law_pos = source.index("## 1. 법령·첨부원본 최신성")
        db_pos = source.index("## 2. 판정용 규정 DB")
        evidence_pos = source.index("## 3. 승인 근거자료 보관")
        readiness_pos = source.index("## 4. 판정진단 준비상태")
        self.assertLess(law_pos, db_pos)
        self.assertLess(db_pos, evidence_pos)
        self.assertLess(evidence_pos, readiness_pos)
        self.assertIn("PDF·HWP/HWPX", source)
        self.assertIn("법제처 최신 법령·첨부원본 확인", source)
        self.assertIn("approve_latest_observation", source)
        self.assertIn("run_law_monitor", source)

    def test_admin_page_distinguishes_freshness_from_pdf_table_extraction(self):
        source = (ROOT / "ui/regdb_page.py").read_text(encoding="utf-8")
        self.assertIn("아래 버튼은 '법령 최신성 조회' 버튼이 아니라 판정 엔진용 구조화 표를 만드는 기능입니다.", source)
        self.assertIn("HWP/HWPX는 원본서식 보존·결과물 작성에 사용합니다", source)
        self.assertIn("판정 DB 근거 PDF 보관 재확인", source)

    def test_explicit_admin_actions_clear_cached_diagnosis_state(self):
        source = (ROOT / "ui/regdb_page.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("st.cache_data.clear()"), 3)

    def test_diagnosis_hold_routes_user_to_the_same_four_step_admin_flow(self):
        source = (ROOT / "ui/diagnosis_entry.py").read_text(encoding="utf-8")
        self.assertIn("PDF·HWP/HWPX", source)
        self.assertIn("규정 DB 관리에서 확인하기", source)
        self.assertIn('st.page_link("ui/regdb_page.py"', source)
        self.assertIn("회사 Excel 입력 오류가 아니라 관리자 법령자료 준비상태", source)


if __name__ == "__main__":
    unittest.main()
