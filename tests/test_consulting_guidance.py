from __future__ import annotations

import unittest

from engine.consulting_guidance import get_guide


class ConsultingGuidanceTests(unittest.TestCase):
    def test_psm_delegated_exclusion_is_resolved(self) -> None:
        guide = get_guide("PSM_EXCLUDED_FACILITY")
        self.assertIsNotNone(guide)
        assert guide is not None
        self.assertIn("비상발전기용 경유의 저장탱크 및 사용설비", guide.what_to_check)
        self.assertIn("제43조제2항제8호", " ".join(guide.legal_hierarchy))
        self.assertIn("제2조의2", " ".join(guide.legal_hierarchy))
        self.assertIn("비상발전기용 경유", guide.resolved_detail)
        self.assertEqual(guide.source_status, "현행 공식 행정규칙 확인")

    def test_core_company_questions_have_plain_language_and_basis(self) -> None:
        for key in (
            "PSM_R_RATIO",
            "PSM_EXCLUDED_FACILITY",
            "PSM_SPECIAL_CONDITION",
            "CAP_MAX_HOLDING",
            "CAP_SPECIAL_CONDITION",
            "CAP_APP1_SDS",
            "CAP_BROAD_SCOPE",
            "DECISION_HOLD",
        ):
            with self.subTest(key=key):
                guide = get_guide(key)
                self.assertIsNotNone(guide)
                assert guide is not None
                self.assertTrue(guide.plain_language.strip())
                self.assertTrue(guide.why_needed.strip())
                self.assertTrue(guide.decision_effect.strip())


if __name__ == "__main__":
    unittest.main()
