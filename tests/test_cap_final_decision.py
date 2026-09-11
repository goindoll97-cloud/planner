import unittest

from engine.cap_final_decision import assess_cap_final


class CAPFinalDecisionTests(unittest.TestCase):
    def test_all_below_lower_is_not_required(self):
        result = assess_cap_final([
            {"status": "BELOW_LOWER", "row_no": 1},
            {"quantity_band": "하위 규정수량 미만", "row_no": 2},
        ])
        self.assertEqual(result.status, "NOT_REQUIRED")

    def test_lower_without_exemption_is_group2(self):
        result = assess_cap_final(
            [{"status": "LOWER_CANDIDATE", "row_no": 1}],
            exemption_answer="NONE",
        )
        self.assertEqual(result.status, "REQUIRED_GROUP_2")
        self.assertEqual(result.group, "2군")

    def test_lower_waits_for_exemption_answer(self):
        result = assess_cap_final([{"status": "LOWER_CANDIDATE", "row_no": 1}])
        self.assertEqual(result.status, "HOLD")
        self.assertIn("면제", result.label)

    def test_confirmed_exemption_is_not_required(self):
        result = assess_cap_final(
            [{"status": "LOWER_CANDIDATE", "row_no": 1}],
            exemption_answer="EXEMPT",
            exemption_key="NOTICE_GAS_STATION",
            exemption_all_relevant_confirmed=True,
        )
        self.assertEqual(result.status, "NOT_REQUIRED")
        self.assertIn("면제", result.label)

    def test_partial_exemption_holds(self):
        result = assess_cap_final(
            [{"status": "LOWER_CANDIDATE", "row_no": 1}],
            exemption_answer="PARTIAL",
        )
        self.assertEqual(result.status, "HOLD")

    def test_upper_requires_major_facility(self):
        result = assess_cap_final(
            [{"status": "UPPER_CANDIDATE", "row_no": 1}],
            exemption_answer="NONE",
        )
        self.assertEqual(result.status, "HOLD")
        self.assertIn("주요취급시설", result.label)

    def test_upper_and_major_facility_is_group1(self):
        result = assess_cap_final(
            [{"status": "UPPER_CANDIDATE", "row_no": 1}],
            exemption_answer="NONE",
            major_facility_answer="YES",
        )
        self.assertEqual(result.status, "REQUIRED_GROUP_1")
        self.assertEqual(result.group, "1군")

    def test_upper_without_major_facility_does_not_force_group2(self):
        result = assess_cap_final(
            [{"status": "UPPER_CANDIDATE", "row_no": 1}],
            exemption_answer="NONE",
            major_facility_answer="NO",
        )
        self.assertEqual(result.status, "HOLD")

    def test_unresolved_fact_blocks_final_decision(self):
        result = assess_cap_final(
            [{"status": "LOWER_CANDIDATE", "row_no": 1}],
            unresolved_blockers=["SDS 확인 필요"],
            exemption_answer="NONE",
        )
        self.assertEqual(result.status, "HOLD")


if __name__ == "__main__":
    unittest.main()
