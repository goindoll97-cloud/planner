from __future__ import annotations

import unittest

from engine.stage2.cap_manual_field_guidance import (
    cap_field_guidance,
    cap_field_guidance_text,
    load_cap_manual_field_guidance,
)


class CapManualFieldGuidanceTests(unittest.TestCase):
    def test_registry_loads_with_expected_schema_version(self):
        raw = load_cap_manual_field_guidance()
        self.assertEqual(raw.get("schema_version"), "cap-manual-field-guidance-v1")
        self.assertIn("fields", raw)

    def test_known_field_returns_its_manual_guidance(self):
        entry = cap_field_guidance("cap.business.writing_level")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["form"], "별지 제3호서식")
        self.assertIn("제4조", entry["guidance"])

    def test_guidance_text_helper_returns_plain_string(self):
        text = cap_field_guidance_text("cap.business.submission_type")
        self.assertIn("제10조", text)

    def test_self_evident_field_has_no_guidance_text(self):
        # 매뉴얼에 별도 작성요령이 없는 자명한 항목(대표자 등)은 guidance가
        # None이어야 하고, 텍스트 헬퍼는 빈 문자열을 돌려줘야 한다 — 호출부가
        # "guidance: None"을 프롬프트에 그대로 흘려보내지 않도록.
        entry = cap_field_guidance("cap.business.representative")
        self.assertIsNotNone(entry)
        self.assertIsNone(entry["guidance"])
        self.assertEqual(cap_field_guidance_text("cap.business.representative"), "")

    def test_unmapped_field_key_returns_none_not_error(self):
        # 3.2~3.6은 아직 미작성이므로, 그 구간 field_key는 존재하되 이
        # 레지스트리엔 없다 — 예외가 아니라 None으로 처리되어야 한다.
        self.assertIsNone(cap_field_guidance("cap.offsite.risk_analysis"))
        self.assertEqual(cap_field_guidance_text("cap.offsite.risk_analysis"), "")

    def test_recent_accident_year_discrepancy_is_recorded_as_resolved(self):
        # 회귀 방지용: 매뉴얼 '5년' vs 규정·코드 '3년' 불일치가 있었고,
        # 3년으로 확정됐다는 결정 이력이 이 파일에 남아있어야 한다 — 나중에
        # 매뉴얼이 다시 개정돼서 이 값을 갱신할 때 왜 3년으로 정했었는지
        # 맥락 없이 덮어쓰지 않도록.
        entry = cap_field_guidance("cap.business.recent_accident")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["resolved_flag"]["decision"].split(" ")[0], "3년")

    def test_group_2_external_response_downstream_rule_is_documented(self):
        entry = cap_field_guidance("cap.business.writing_level")
        self.assertIn("2군", entry["downstream_rule"])
        self.assertIn("외부비상대응계획", entry["downstream_rule"])


if __name__ == "__main__":
    unittest.main()
