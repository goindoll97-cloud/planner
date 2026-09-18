from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage2ReviewSimplifiedUITests(unittest.TestCase):
    def test_stage5_is_single_report_writing_page(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn('st.title("📝 5. 보고서 작성")', text)
        self.assertNotIn("WORK_AREAS", text)
        self.assertNotIn("st.radio(\n    \"작성·검토 작업\"", text)
        self.assertNotIn("부족자료", text)
        self.assertIn("DOCX 보고서 내려받기", text)

    def test_ai_is_optional_and_explained_in_user_language(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("AI로 문장 다듬은 초안 만들기", text)
        self.assertNotIn("AI로 문장 다듬은 초안도 만들기", text)
        self.assertIn("법적 판정이나 회사자료를 바꾸지 않고", text)
        self.assertIn("DOCX 보고서를 작성합니다", text)
        self.assertNotIn("`AI 문장보강`", text)

    def test_basic_downloads_render_before_optional_ai_work(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        download_index = text.index('st.markdown("## DOCX 보고서 내려받기")')
        ai_index = text.index('st.markdown("### AI로 문장 다듬기 · 선택사항")')
        self.assertLess(download_index, ai_index)
        self.assertIn("AI를 실행하지 않아도 확인된 자료를 반영한 DOCX를 바로 내려받을 수 있습니다.", text)

    def test_ai_work_shows_count_progress_and_requires_explicit_start(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("AI로 정리할 설명문: {pending_total}개", text)
        self.assertIn("AI 문장 다듬기 시작 · {pending_total}개", text)
        self.assertIn("st.progress(0.0", text)
        self.assertIn("progress.progress", text)
        self.assertIn("recommended_batch_size", text)
        self.assertIn("ui_batch_size = recommended_batch_size", text)
        self.assertNotIn("AI_UI_BATCH_SIZE = 3", text)

    def test_auto_ai_skips_already_confirmed_narrative(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("def _automatic_ai_candidates", text)
        self.assertIn("CONFIRMED_STATUSES", text)
        self.assertIn("if not has_confirmed_narrative", text)
        self.assertIn("이미 입력된 회사 설명문과 표는 다시 생성하지 않습니다", text)

    def test_report_downloads_offer_plain_and_ai_enhanced_drafts(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("검토용 DOCX 다운로드", text)
        self.assertIn("AI 문장 검토용 내부 DOCX", text)
        self.assertIn("build_report_draft", text)
        self.assertIn("build_ai_enhanced_report_draft", text)

    def test_cap_output_is_docx_only_and_does_not_require_hwpx_setup(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("화학사고예방관리계획서 · DOCX 작성본", text)
        self.assertIn("HWPX를 생성하지 않고 DOCX를 기본 출력으로 사용", text)
        self.assertNotIn("build_cap_hwpx_draft", text)
        self.assertNotIn("법제처 원본 HWPX가 이 실행환경에 아직 준비되지 않았습니다", text)
        self.assertNotIn("원본서식 등록", text)

    def test_stage5_separates_docx_authoring_from_final_submission_readiness(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("validate_selected_scope", text)
        self.assertIn("report.final_export_allowed", text)
        self.assertIn("보고서 본문 작성자료 확인은 완료되었지만 최종 제출자료 준비는 아직 완료되지 않았습니다", text)
        self.assertIn("프로그램 검증 기준상 제출 전 자료점검이 완료되었습니다", text)
        self.assertIn("DOCX 작성 가능 상태와 최종 제출자료 준비 완료 상태는 별도로 표시합니다", text)
        self.assertIn("공정안전보고서 규정서식 검토용 DOCX 다운로드", text)

    def test_stage4_does_not_count_non_applicable_forms_as_unresolved(self):
        text = (ROOT / "ui/stage2_validation_page.py").read_text(encoding="utf-8")
        self.assertIn("CAP_FORM_NOT_APPLICABLE", text)
        self.assertIn("item.state not in {CAP_FORM_READY, CAP_FORM_NOT_APPLICABLE}", text)

    def test_stage4_uses_practical_labels_and_explains_what_is_checked(self):
        text = (ROOT / "ui/stage2_validation_page.py").read_text(encoding="utf-8")
        self.assertIn('st.title("🔎 4. 작성자료 점검·보완")', text)
        self.assertIn("필요한 자료가 빠지지 않았는지", text)
        self.assertIn("회사정보·화학물질·시설·표의 내용이 서로 맞는지", text)
        self.assertIn('"HOLD": "보완 필요"', text)
        self.assertIn('"REVIEW_REQUIRED": "담당자 확인 필요"', text)
        self.assertIn('"PASS": "확인 완료"', text)

    def test_stage4_contains_reinforcement_requests_and_no_json_download(self):
        text = (ROOT / "ui/stage2_validation_page.py").read_text(encoding="utf-8")
        self.assertIn("### 보강 요청자료", text)
        self.assertIn("추가로 필요한 자료", text)
        self.assertIn("담당자 요청내용", text)
        self.assertNotIn("JSON 다운로드", text)
        self.assertNotIn("application/json", text)
        self.assertNotIn("json.dumps", text)

    def test_stage5_defensively_requires_stage4_completion(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("validation_confirmed", text)
        self.assertIn("4. 작성자료 점검·보완", text)


if __name__ == "__main__":
    unittest.main()
