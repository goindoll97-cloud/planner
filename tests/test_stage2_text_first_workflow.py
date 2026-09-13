from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2.ai_drafting import ai_draftable_specs
from engine.stage2.guidance import build_requirement_guidance
from engine.stage2.intake import build_intake_catalog
from engine.stage2.project import Stage2Project
from engine.stage2.workflow import (
    ATTACHMENT_MODE_MANUAL,
    ATTACHMENT_MODE_PROGRAM,
    BUCKET_AI_TEXT,
    BUCKET_CORE_INPUT,
    BUCKET_MANUAL_ATTACHMENT,
    attachment_mode,
    intake_confirmed,
    mark_intake_confirmed,
    mark_validation_confirmed,
    set_attachment_mode,
    stage3_bucket,
    validation_confirmed,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Stage2TextFirstWorkflowTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-TEXT-FIRST",
            company_name="테스트화학",
            psm_required=True,
            cap_required=True,
            cap_group="2군",
            scope_confirmed=True,
            psm_selected=True,
            cap_selected=True,
        )
        project.set_field("business.company_name", "회사명", "테스트화학", "USER_CONFIRMED")
        project.set_field("business.address", "사업장 소재지", "테스트시 1", "USER_CONFIRMED")
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{"물질명": "톨루엔", "CAS 번호": "108-88-3", "최대보유량": 1000, "단위": "kg"}],
            "USER_CONFIRMED",
        )
        project.set_field(
            "inventory.facilities",
            "시설·설비 목록",
            [{"설비번호": "TK-101", "설비명": "저장탱크", "설비종류": "저장탱크"}],
            "USER_CONFIRMED",
        )
        project.set_field(
            "process.description",
            "공정설명서",
            "원료를 저장탱크에 저장한 후 공정으로 이송한다.",
            "USER_CONFIRMED",
        )
        return project

    def _item(self, project: Stage2Project, requirement_key: str):
        return next(item for item in build_intake_catalog(project) if item.requirement_key == requirement_key)

    def test_manual_attachment_mode_is_default(self):
        self.assertEqual(attachment_mode(self._project()), ATTACHMENT_MODE_MANUAL)

    def test_attachment_items_are_deferred_in_manual_mode(self):
        project = self._project()
        pfd = self._item(project, "common.pfd")
        guidance = build_requirement_guidance(project, pfd)
        self.assertEqual(stage3_bucket(project, pfd, guidance), BUCKET_MANUAL_ATTACHMENT)

        fireproofing = self._item(project, "psm.psi.fireproofing")
        guidance = build_requirement_guidance(project, fireproofing)
        self.assertEqual(stage3_bucket(project, fireproofing, guidance), BUCKET_MANUAL_ATTACHMENT)

    def test_static_company_tables_remain_core_inputs(self):
        project = self._project()
        machinery = self._item(project, "psm.psi.machinery")
        guidance = build_requirement_guidance(project, machinery)
        self.assertEqual(stage3_bucket(project, machinery, guidance), BUCKET_CORE_INPUT)

    def test_missing_report_narrative_is_ai_text_candidate(self):
        project = self._project()
        risk = self._item(project, "psm.risk.mitigation")
        guidance = build_requirement_guidance(project, risk)
        self.assertEqual(stage3_bucket(project, risk, guidance), BUCKET_AI_TEXT)

    def test_local_ai_can_draft_text_for_mixed_manual_attachment_item(self):
        project = self._project()
        keys = {spec.key for spec in ai_draftable_specs(project, "PSM")}
        self.assertIn("psm.psi.fireproofing", keys)
        self.assertNotIn("psm.psi.pid", keys)

        set_attachment_mode(project, ATTACHMENT_MODE_PROGRAM)
        keys = {spec.key for spec in ai_draftable_specs(project, "PSM")}
        self.assertNotIn("psm.psi.fireproofing", keys)

    def test_workflow_gates_progress_sequentially(self):
        project = self._project()
        self.assertFalse(intake_confirmed(project))
        self.assertFalse(validation_confirmed(project))
        mark_intake_confirmed(project, True)
        self.assertTrue(intake_confirmed(project))
        self.assertFalse(validation_confirmed(project))
        mark_validation_confirmed(project, True)
        self.assertTrue(validation_confirmed(project))
        set_attachment_mode(project, ATTACHMENT_MODE_PROGRAM)
        self.assertFalse(intake_confirmed(project))
        self.assertFalse(validation_confirmed(project))

    def test_navigation_and_intake_ui_are_progress_gated(self):
        app = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        intake = (PROJECT_ROOT / "ui/stage2_intake_page.py").read_text(encoding="utf-8")
        validation = (PROJECT_ROOT / "ui/stage2_validation_page.py").read_text(encoding="utf-8")
        self.assertIn("if intake_ready:", app)
        self.assertIn("if validation_ready:", app)
        self.assertIn("도면·이미지·첨부자료는 담당자가 별도 작성·취합", intake)
        self.assertIn("텍스트·표 자료 준비 완료 → 4. 작성자료 교차검증 열기", intake)
        self.assertIn("교차검증 확인 완료 → 5. 작성·검토 열기", validation)

    def test_reference_tools_are_not_numbered_workflow_stages(self):
        app = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        legal_page = (PROJECT_ROOT / "ui/legal_evidence_page.py").read_text(encoding="utf-8")
        self.assertIn('title="규정 DB 관리"', app)
        self.assertIn('title="법령·근거 라이브러리"', app)
        self.assertNotIn('title="6. 규정 DB 관리"', app)
        self.assertNotIn('title="7. 법령·근거 라이브러리"', app)
        self.assertNotIn('st.title("📚 7. 법령·근거 라이브러리")', legal_page)
        self.assertIn('st.title("📚 법령·근거 라이브러리")', legal_page)


if __name__ == "__main__":
    unittest.main()
