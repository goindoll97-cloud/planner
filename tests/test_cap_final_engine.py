import unittest

from engine.cap_final_engine import decide_cap_final


class CAPFinalEngineTests(unittest.TestCase):
    def test_all_below_lower_is_not_required(self):
        result = decide_cap_final(
            ["BELOW_LOWER", "NOT_APP1"],
            all_quantity_facts_resolved=True,
        )
        self.assertFalse(result.requires_plan)
        self.assertEqual(result.status, "NOT_REQUIRED_QUANTITY")

    def test_lower_no_exemption_is_group2(self):
        result = decide_cap_final(
            ["LOWER_CANDIDATE", "BELOW_LOWER"],
            all_quantity_facts_resolved=True,
            exemption_code="NONE",
        )
        self.assertTrue(result.requires_plan)
        self.assertEqual(result.group, "2군")
        self.assertEqual(result.status, "REQUIRED_2")

    def test_upper_and_major_facility_is_group1(self):
        result = decide_cap_final(
            ["UPPER_CANDIDATE"],
            all_quantity_facts_resolved=True,
            exemption_code="NONE",
            major_facility_answer="YES",
        )
        self.assertTrue(result.requires_plan)
        self.assertEqual(result.group, "1군")
        self.assertEqual(result.status, "REQUIRED_1")

    def test_upper_without_major_facility_confirmation_requires_plan_but_group_holds(self):
        result = decide_cap_final(
            ["UPPER_CANDIDATE"],
            all_quantity_facts_resolved=True,
            exemption_code="NONE",
            major_facility_answer="UNKNOWN",
        )
        self.assertTrue(result.requires_plan)
        self.assertIsNone(result.group)
        self.assertEqual(result.status, "REQUIRED_GROUP_HOLD")

    def test_verified_exemption_is_not_required(self):
        result = decide_cap_final(
            ["LOWER_CANDIDATE"],
            all_quantity_facts_resolved=True,
            exemption_code="RULE19_2_5_MEDICAL",
            all_relevant_facilities_covered_by_exemption=True,
        )
        self.assertFalse(result.requires_plan)
        self.assertEqual(result.status, "NOT_REQUIRED_EXEMPT")

    def test_partial_exemption_scope_does_not_exempt_whole_site(self):
        result = decide_cap_final(
            ["LOWER_CANDIDATE"],
            all_quantity_facts_resolved=True,
            exemption_code="RULE19_2_5_MEDICAL",
            all_relevant_facilities_covered_by_exemption=False,
        )
        self.assertIsNone(result.requires_plan)
        self.assertEqual(result.status, "HOLD_EXEMPTION_SCOPE")

    def test_unresolved_quantity_stays_hold(self):
        result = decide_cap_final(
            ["LOWER_CANDIDATE", "HOLD"],
            all_quantity_facts_resolved=False,
            exemption_code="NONE",
        )
        self.assertIsNone(result.requires_plan)
        self.assertEqual(result.status, "HOLD")


if __name__ == "__main__":
    unittest.main()
