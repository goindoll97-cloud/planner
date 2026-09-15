from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage2ReviewSimplifiedUITests(unittest.TestCase):
    def test_review_page_has_only_three_primary_work_areas(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn('WORK_AREAS = ("부족자료", "AI 문장보강", "보고서 초안 생성")', text)
        self.assertIn("st.radio(", text)
        self.assertNotIn("st.tabs(", text)
        for retired in ("작성현황", "확인값·초안 관리", "감사·검토자료"):
            self.assertNotIn(f'"{retired}"', text)

    def test_ai_generation_is_automatic_not_button_driven(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("_run_automatic_ai", text)
        self.assertIn("generate_system_ai_drafts", text)
        self.assertIn("별도 생성 버튼 없이", text)
        self.assertNotIn("로컬 AI 문장 보강 생성", text)

    def test_non_ai_work_areas_do_not_execute_ai_generation(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn('elif work_area == "AI 문장보강":', text)
        self.assertIn("_render_ai_status(project)", text)
        self.assertIn("AI를 기다리지 않고 바로", text)

    def test_fast_auto_model_is_available_without_changing_precision_model(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("select_fast_auto_config", text)
        self.assertIn("자동 문장보강은 속도 우선 모델 사용", text)
        self.assertIn("기본 정밀 모델", text)
        self.assertIn("requirement_keys=[spec.key for spec in missing]", text)

    def test_report_downloads_offer_plain_and_ai_enhanced_drafts(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("AI 보강 없음", text)
        self.assertIn("AI 보강 포함", text)
        self.assertIn("build_report_draft", text)
        self.assertIn("build_ai_enhanced_report_draft", text)

    def test_ai_work_area_reference_uses_normal_text_not_inline_code_font(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertNotIn("`AI 문장보강`", text)
        self.assertIn("AI 문장보강 영역을 한 번 열면", text)

    def test_missing_cap_hwpx_guides_user_to_legal_db_update(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("법제처 원본 HWPX가 이 실행환경에 아직 준비되지 않았습니다", text)
        self.assertIn('st.page_link(\n            "ui/regdb_page.py"', text)
        self.assertIn("규정 DB 관리에서 법제처 최신 원본 준비", text)
        self.assertIn("최신본 업데이트", text)

    def test_stage5_defensively_requires_stage4_confirmation(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("validation_confirmed", text)
        self.assertIn("4. 작성자료 교차검증", text)


if __name__ == "__main__":
    unittest.main()
