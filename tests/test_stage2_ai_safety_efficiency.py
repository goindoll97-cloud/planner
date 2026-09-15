from __future__ import annotations

import unittest

from engine.stage2.ai_drafting import (
    _build_pack_prompt,
    ai_draft_field_key,
    ai_draft_is_current,
    ai_draftable_specs,
    generate_system_ai_drafts,
)
from engine.stage2.ai_report import has_ai_report_prose
from engine.stage2.project import Stage2Project


SAFETY_MANAGEMENT_REQUIREMENT = "cap.prevention.safety_management"


class FakeLLMClient:
    model = "fake-grounded-model"

    def __init__(self, payload):
        self.payload = payload

    def generate_json(self, *, instructions: str, prompt: str):
        return self.payload


class Stage2AISafetyEfficiencyTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-AI-SAFE-EFFICIENT",
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
            "유해화학물질 사고 예방과 설비건전성 및 비상대응 강화를 안전관리 방향으로 운영한다.",
            "USER_CONFIRMED",
        )
        return project

    def _safe_payload(self):
        return {
            "profile_summary": "확인된 사업장 안전관리 특성",
            "drafts": [
                {
                    "requirement_key": SAFETY_MANAGEMENT_REQUIREMENT,
                    "draft_text": "본 사업장은 확인된 안전관리 방향에 따라 유해화학물질 사고 예방활동을 운영한다.",
                    "suggested_additions": [],
                    "used_fact_keys": ["cap.prevention.safety_policy"],
                }
            ],
        }

    def test_confirmed_fact_change_invalidates_cached_ai_draft_and_report_overlay(self):
        project = self._project()
        generate_system_ai_drafts(project, "CAP", FakeLLMClient(self._safe_payload()))

        key = ai_draft_field_key("CAP", SAFETY_MANAGEMENT_REQUIREMENT)
        record = project.get_field(key)
        self.assertIsNotNone(record)
        self.assertTrue(record.value.get("input_facts_sha256"))
        self.assertTrue(ai_draft_is_current(project, "CAP", SAFETY_MANAGEMENT_REQUIREMENT))
        self.assertTrue(has_ai_report_prose(project, "CAP"))

        project.set_field(
            "inventory.facilities",
            "시설·설비 목록",
            [
                {"설비번호": "TK-101", "설비명": "톨루엔 저장탱크"},
                {"설비번호": "P-201", "설비명": "이송펌프"},
            ],
            "VERIFIED",
        )

        self.assertFalse(ai_draft_is_current(project, "CAP", SAFETY_MANAGEMENT_REQUIREMENT))
        self.assertFalse(has_ai_report_prose(project, "CAP"))

    def test_qualitative_draft_without_fact_link_is_rejected(self):
        project = self._project()
        payload = self._safe_payload()
        payload["drafts"][0]["used_fact_keys"] = []

        result = generate_system_ai_drafts(project, "CAP", FakeLLMClient(payload))

        self.assertEqual(len(result.generated), 0)
        self.assertEqual(len(result.rejected), 1)
        self.assertTrue(
            any("used_fact_keys" in warning for warning in result.rejected[0].validation_warnings)
        )

    def test_prompt_uses_single_fact_catalog_instead_of_per_item_fact_copies(self):
        project = self._project()
        spec = next(
            spec
            for spec in ai_draftable_specs(project, "CAP")
            if spec.key == SAFETY_MANAGEMENT_REQUIREMENT
        )
        prompt, facts = _build_pack_prompt(project, "CAP", [spec])

        self.assertIn('"confirmed_fact_catalog"', prompt)
        self.assertIn('"confirmed_fact_keys"', prompt)
        self.assertNotIn('"global_confirmed_facts"', prompt)
        self.assertNotIn('"confirmed_facts"', prompt)
        self.assertIn("cap.prevention.safety_policy", facts)


if __name__ == "__main__":
    unittest.main()
