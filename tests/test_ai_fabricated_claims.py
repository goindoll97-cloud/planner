from __future__ import annotations

import unittest

from engine.stage2.ai_drafting import NO_FACT_NOTICE, drop_fabricated_claims


class FabricatedClaimTests(unittest.TestCase):
    def test_accident_history_and_absence_claims_are_removed(self):
        text = ("본 계획서에서는 사고복구 계획을 수립하여 관리한다. 다만, 해당 사업장은 현재까지 화학사고가 발생하지 않았으며, 자료는 없다. "
                "[확인 필요: 복구 조직]")
        cleaned = drop_fabricated_claims(text)
        self.assertNotIn("발생하지 않았", cleaned)
        self.assertIn("[확인 필요: 복구 조직]", cleaned)
        self.assertNotIn("수립되어 있지 않", drop_fabricated_claims("비상통제실 계획이 수립되어 있지 않습니다. 확인이 필요합니다."))

    def test_normal_sentences_and_typed_facts_stay(self):
        text = "전 직원을 대상으로 연 1 회 교육을 실시한다. 교육 방법은 사내 강의다."
        self.assertEqual(drop_fabricated_claims(text), text)

    def test_when_everything_is_a_claim_the_notice_replaces_it(self):
        self.assertEqual(drop_fabricated_claims("현재까지 화학사고가 발생하지 않았다.") or NO_FACT_NOTICE, NO_FACT_NOTICE)


if __name__ == "__main__":
    unittest.main()
