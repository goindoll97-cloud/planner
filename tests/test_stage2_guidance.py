from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2.guidance import (
    ACTION_EXCEL,
    ACTION_FILE,
    all_requirement_specs_for_library,
    build_requirement_guidance,
    requirement_library_search_text,
)
from engine.stage2.intake import build_intake_catalog
from engine.stage2.project import create_project_from_stage1_snapshot


class Stage2GuidanceTests(unittest.TestCase):
    def _project(self):
        snapshot = {
            "source_fingerprint": "a" * 64,
            "business": {
                "회사명": "테스트회사",
                "사업장명": "테스트공장",
                "사업장 소재지": "테스트시 테스트구 1",
            },
            "documents": {},
            "chemicals": [{"제품명": "톨루엔", "CAS No.": "108-88-3"}],
            "facilities": [{"시설명": "TK-101", "시설유형": "저장탱크"}],
            "decision": {
                "psm_status": "공정안전보고서 제출 대상",
                "cap_status": "작성수준 — 1군 사업장",
            },
        }
        project = create_project_from_stage1_snapshot(snapshot)
        project.set_authoring_scope(psm_selected=True, cap_selected=True)
        return project

    def test_common_process_description_points_to_integrated_workbook(self):
        project = self._project()
        item = next(row for row in build_intake_catalog(project) if row.requirement_key == "common.process_description")
        guidance = build_requirement_guidance(project, item)
        self.assertEqual(guidance.action_type, ACTION_EXCEL)
        self.assertIn("06_공정정보", guidance.workbook_locations)
        self.assertIn("추가 작성", guidance.action_text)

    def test_common_pfd_is_file_action_and_has_traceable_basis_or_guidance(self):
        project = self._project()
        item = next(row for row in build_intake_catalog(project) if row.requirement_key == "common.pfd")
        guidance = build_requirement_guidance(project, item)
        self.assertEqual(guidance.action_type, ACTION_FILE)
        self.assertIn("07_도면_첨부자료목록", guidance.workbook_locations)
        self.assertTrue(
            guidance.statutory_bases or guidance.detailed_bases or guidance.references,
            "공정흐름도(PFD)는 선택된 보고서의 구조화 근거 또는 작성 참고자료와 연결되어야 합니다.",
        )

    def test_legal_library_can_find_process_flow_diagram(self):
        specs = all_requirement_specs_for_library()
        matches = [spec for spec in specs if "공정흐름도" in requirement_library_search_text(spec)]
        self.assertTrue(matches)
        self.assertTrue(any("documents.pfd" in spec.field_keys for spec in matches))

    def test_legal_library_remains_separate_from_company_intake(self):
        intake = Path("ui/stage2_intake_page.py").read_text(encoding="utf-8")
        library = Path("ui/legal_evidence_page.py").read_text(encoding="utf-8")
        app = Path("app.py").read_text(encoding="utf-8")

        self.assertNotIn("해야 할 일·작성상태 확인", intake)
        self.assertNotIn("법적 의무 근거", intake)
        self.assertNotIn("_legal_focus_requirement_key", intake)
        self.assertNotIn("st.switch_page(\"ui/legal_evidence_page.py\")", intake)
        self.assertIn("추가로 필요한 항목", intake)

        self.assertIn("작성항목 근거 검색", library)
        self.assertIn("_legal_focus_requirement_key", library)
        self.assertIn("법령·근거 라이브러리", app)


if __name__ == "__main__":
    unittest.main()
