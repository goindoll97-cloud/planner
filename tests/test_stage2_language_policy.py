from __future__ import annotations

import unittest

from engine.stage2.ai_drafting import generate_system_ai_drafts
from engine.stage2.language_policy import (
    assert_public_prose,
    language_policy_for_prompt,
    normalize_public_prose,
    validate_public_prose,
)
from engine.stage2.project import Stage2Project


SAFETY_MANAGEMENT_REQUIREMENT = "cap.prevention.safety_management"


class FakeLLMClient:
    model = "local-test-model"

    def __init__(self, payload):
        self.payload = payload
        self.instructions = ""
        self.prompt = ""

    def generate_json(self, *, instructions: str, prompt: str):
        self.instructions = instructions
        self.prompt = prompt
        return self.payload


class Stage2LegalLanguagePolicyTests(unittest.TestCase):
    def _cap_project(self) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-LANGUAGE-CAP2",
            company_name="테스트화학",
            psm_required=False,
            cap_required=True,
            cap_group="2군",
            scope_confirmed=True,
            psm_selected=False,
            cap_selected=True,
        )
        project.set_field(
            "cap.prevention.safety_policy",
            "안전관리 방침·목표",
            "유해화학물질 사고 예방과 설비건전성, 변경관리 및 비상대응을 안전관리 방향으로 운영한다.",
            "USER_CONFIRMED",
        )
        return project

    def test_psm_prompt_policy_contains_current_legal_terms(self):
        policy = language_policy_for_prompt("PSM")
        self.assertEqual(policy["program"], "공정안전보고서")
        self.assertIn("공정안전자료", policy["canonical_sections"])
        self.assertIn("공정위험성평가서", policy["canonical_sections"])
        self.assertIn("안전운전계획", policy["canonical_sections"])
        self.assertIn("비상조치계획", policy["canonical_sections"])
        self.assertIn("변경요소 관리계획", policy["canonical_terms"])
        self.assertIn("설비점검·검사 및 보수계획, 유지계획 및 지침서", policy["canonical_terms"])

    def test_cap_prompt_policy_contains_current_legal_terms(self):
        policy = language_policy_for_prompt("CAP")
        self.assertEqual(policy["program"], "화학사고예방관리계획서")
        self.assertIn("사전관리방침", policy["canonical_sections"])
        self.assertIn("내부 비상대응계획", policy["canonical_sections"])
        self.assertIn("외부 비상대응계획", policy["canonical_sections"])
        self.assertIn("2군 사업장", policy["canonical_terms"])

    def test_unambiguous_legacy_terms_are_normalized(self):
        text = normalize_public_prose(
            "내부 비상대응 계획과 비상장비·인력 보유현황을 검토한다.",
            "CAP",
        )
        self.assertIn("내부 비상대응계획", text)
        self.assertIn("비상조치를 위한 장비·인력 보유현황", text)
        self.assertNotIn("내부 비상대응 계획", text)
        self.assertEqual(validate_public_prose(text, "CAP"), ())

    def test_developer_terms_and_internal_keys_are_blocked(self):
        warnings = validate_public_prose(
            "requirement_key와 cap.prevention.safety_policy payload를 mapping한다.",
            "CAP",
        )
        joined = " ".join(warnings)
        self.assertIn("개발자 내부용어", joined)
        self.assertIn("내부 필드명/키", joined)
        with self.assertRaisesRegex(ValueError, "용어검사"):
            assert_public_prose("AI_DRAFT 상태의 field_key를 사용한다.", "PSM")

    def test_grounded_generation_rejects_developer_language(self):
        project = self._cap_project()
        client = FakeLLMClient({
            "profile_summary": "2군 사업장",
            "drafts": [
                {
                    "requirement_key": SAFETY_MANAGEMENT_REQUIREMENT,
                    "draft_text": "확인된 payload를 mapping하여 안전관리 방침을 구성한다.",
                    "suggested_additions": [],
                    "used_fact_keys": ["cap.prevention.safety_policy"],
                }
            ],
        })

        result = generate_system_ai_drafts(project, "CAP", client)
        self.assertEqual(len(result.generated), 0)
        self.assertEqual(len(result.rejected), 1)
        self.assertTrue(any("개발자 내부용어" in warning for warning in result.rejected[0].validation_warnings))
        self.assertIn("정식 법령·행정규칙 용어", client.instructions)
        self.assertIn("terminology_policy", client.prompt)


if __name__ == "__main__":
    unittest.main()
