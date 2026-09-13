from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest

from docx import Document

from engine.stage2.ai_drafting import (
    ai_draft_field_key,
    ai_draftable_specs,
    approve_ai_draft,
    build_operating_profile,
    generate_system_ai_drafts,
)
from engine.stage2.ai_report import build_ai_enhanced_report_draft, has_ai_report_prose
from engine.stage2.project import Stage2Project


SAFETY_MANAGEMENT_REQUIREMENT = "cap.prevention.safety_management"
SELF_INSPECTION_REQUIREMENT = "cap.prevention.self_inspection"


class FakeLLMClient:
    model = "fake-grounded-model"

    def __init__(self, payload):
        self.payload = payload
        self.instructions = ""
        self.prompt = ""

    def generate_json(self, *, instructions: str, prompt: str):
        self.instructions = instructions
        self.prompt = prompt
        return self.payload


class Stage2GroundedAIDraftingTests(unittest.TestCase):
    def _cap_group2_project(self) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-AI-CAP2",
            company_name="테스트화학",
            psm_required=False,
            cap_required=True,
            cap_group="2군",
            scope_confirmed=True,
            psm_selected=False,
            cap_selected=True,
        )
        project.set_field("business.company_name", "회사명", "테스트화학", "VERIFIED")
        project.set_field("business.address", "사업장 소재지", "울산광역시 테스트로 1", "VERIFIED")
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{"물질명": "톨루엔", "CAS 번호": "108-88-3", "최대보유량": 15000, "단위": "kg"}],
            "VERIFIED",
        )
        project.set_field(
            "inventory.facilities",
            "시설·설비 목록",
            [{"설비번호": "TK-101", "설비명": "톨루엔 저장탱크"}],
            "VERIFIED",
        )
        project.set_field(
            "cap.prevention.safety_policy",
            "안전관리 방침·목표",
            "유해화학물질 누출·화재·폭발 사고 예방과 설비건전성, 작업자 역량, 변경관리, 비상대응 강화를 안전관리 방향으로 운영한다.",
            "USER_CONFIRMED",
        )
        project.set_field(
            "cap.prevention.self_inspection_plan",
            "자체점검계획",
            "취급시설과 방재시설의 상태를 정기적으로 점검하고 부적합은 개선조치로 관리한다.",
            "USER_CONFIRMED",
        )
        return project

    def test_group2_scope_is_fixed_and_external_emergency_is_not_draftable(self):
        project = self._cap_group2_project()
        specs = ai_draftable_specs(project, "CAP")
        keys = {spec.key for spec in specs}

        self.assertIn(SAFETY_MANAGEMENT_REQUIREMENT, keys)
        self.assertIn(SELF_INSPECTION_REQUIREMENT, keys)
        self.assertFalse(any(key.startswith("cap.external.") for key in keys))

        profile = build_operating_profile(project)
        self.assertEqual(profile["cap_group"], "2군")
        self.assertEqual(profile["chemical_count"], 1)
        self.assertIn("톨루엔", profile["major_chemical_names"])

    def test_safe_llm_draft_is_stored_separately_without_overwriting_company_fact(self):
        project = self._cap_group2_project()
        original = project.get_field("cap.prevention.safety_policy").value
        client = FakeLLMClient({
            "profile_summary": "인화성 물질을 취급하고 설비건전성과 비상대응을 중시하는 2군 사업장",
            "drafts": [
                {
                    "requirement_key": SAFETY_MANAGEMENT_REQUIREMENT,
                    "draft_text": "본 사업장은 유해화학물질의 누출·화재·폭발 사고를 예방하고 설비건전성, 작업자 역량, 변경관리 및 비상대응을 주요 안전관리 방향으로 운영한다.",
                    "suggested_additions": ["안전관리 목표의 확인 가능한 성과지표가 있으면 추가 확인"],
                    "used_fact_keys": ["cap.prevention.safety_policy"],
                }
            ],
        })

        result = generate_system_ai_drafts(project, "CAP", client)
        self.assertEqual(len(result.generated), 1)
        self.assertEqual(len(result.rejected), 0)
        self.assertEqual(project.get_field("cap.prevention.safety_policy").value, original)

        key = ai_draft_field_key("CAP", SAFETY_MANAGEMENT_REQUIREMENT)
        record = project.get_field(key)
        self.assertIsNotNone(record)
        self.assertEqual(record.status, "AI_DRAFT")
        self.assertIn("2군", client.prompt)
        self.assertIn("절대 만들어내지 않는다", client.instructions)

    def test_new_numeric_fact_is_rejected_and_not_saved(self):
        project = self._cap_group2_project()
        client = FakeLLMClient({
            "profile_summary": "2군 사업장",
            "drafts": [
                {
                    "requirement_key": SELF_INSPECTION_REQUIREMENT,
                    "draft_text": "사업장은 방재시설을 연 2회 점검하고 결과를 개선조치로 관리한다.",
                    "suggested_additions": [],
                    "used_fact_keys": ["cap.prevention.self_inspection_plan"],
                }
            ],
        })

        result = generate_system_ai_drafts(project, "CAP", client)
        self.assertEqual(len(result.generated), 0)
        self.assertEqual(len(result.rejected), 1)
        self.assertTrue(any("확인자료에 없는 수치" in warning for warning in result.rejected[0].validation_warnings))
        self.assertIsNone(project.get_field(ai_draft_field_key("CAP", SELF_INSPECTION_REQUIREMENT)))

    def test_approval_revalidates_edited_text_and_prevents_new_equipment_tag(self):
        project = self._cap_group2_project()
        client = FakeLLMClient({
            "profile_summary": "2군 사업장",
            "drafts": [
                {
                    "requirement_key": SAFETY_MANAGEMENT_REQUIREMENT,
                    "draft_text": "본 사업장은 확인된 안전관리 방향에 따라 유해화학물질 사고 예방활동을 운영한다.",
                    "suggested_additions": [],
                    "used_fact_keys": ["cap.prevention.safety_policy"],
                }
            ],
        })
        generate_system_ai_drafts(project, "CAP", client)

        with self.assertRaisesRegex(ValueError, "확인자료에 없는"):
            approve_ai_draft(
                project,
                "CAP",
                SAFETY_MANAGEMENT_REQUIREMENT,
                "신규 설비 R-999를 활용하여 사고를 예방한다.",
            )

        approve_ai_draft(
            project,
            "CAP",
            SAFETY_MANAGEMENT_REQUIREMENT,
            "본 사업장은 확인된 안전관리 방향에 따라 유해화학물질 사고 예방활동을 운영한다.",
        )
        record = project.get_field(ai_draft_field_key("CAP", SAFETY_MANAGEMENT_REQUIREMENT))
        self.assertEqual(record.status, "USER_CONFIRMED")

    def test_ai_enhanced_docx_keeps_source_fact_and_inserts_ai_prose(self):
        project = self._cap_group2_project()
        client = FakeLLMClient({
            "profile_summary": "2군 사업장",
            "drafts": [
                {
                    "requirement_key": SAFETY_MANAGEMENT_REQUIREMENT,
                    "draft_text": "본 사업장은 확인된 안전관리 방향을 중심으로 유해화학물질 사고 예방활동을 체계적으로 운영한다.",
                    "suggested_additions": ["성과 확인방법 추가 확인"],
                    "used_fact_keys": ["cap.prevention.safety_policy"],
                }
            ],
        })
        generate_system_ai_drafts(project, "CAP", client)

        self.assertTrue(has_ai_report_prose(project, "CAP"))
        doc = Document(BytesIO(build_ai_enhanced_report_draft(project, "CAP")))
        text = "\n".join([p.text for p in doc.paragraphs] + [cell.text for table in doc.tables for row in table.rows for cell in row.cells])
        self.assertIn("AI 보강 초안 · 사람 검토 필요", text)
        self.assertIn("체계적으로 운영한다", text)
        self.assertIn("누출·화재·폭발 사고 예방", text)
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        self.assertNotIn("외부 비상대응계획", headings)

    def test_review_page_exposes_grounded_ai_workflow(self):
        source = Path("ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn('"AI 문장 보강"', source)
        self.assertIn("generate_system_ai_drafts", source)
        self.assertIn("담당자 검토·승인", source)
        self.assertIn("AI 보강 검토용 DOCX", source)
        self.assertIn("OPENAI_API_KEY", source)


if __name__ == "__main__":
    unittest.main()
