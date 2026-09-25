from __future__ import annotations

import unittest

from engine.stage2.cap_rule29_followup import (
    CHANGE_PERMISSION,
    CHANGE_REPORT,
    suggest_rule29_followup,
)


class CAPRule29FollowupTests(unittest.TestCase):
    def test_permit_lower_quantity_is_change_permission(self):
        result = suggest_rule29_followup({
            "business_status": "영업허가",
            "chemical_added_or_amount_increased": "예",
            "transport_business": "아니오",
            "quantity_band": "하위 이상",
        })
        self.assertIn(CHANGE_PERMISSION, result.actions)
        self.assertIn("제29조제1항제1호다목", " ".join(result.legal_basis))

    def test_permit_between_lowest_and_lower_is_change_report(self):
        result = suggest_rule29_followup({
            "business_status": "영업허가",
            "chemical_added_or_amount_increased": "예",
            "transport_business": "아니오",
            "quantity_band": "최하위 이상·하위 미만",
        })
        self.assertIn(CHANGE_REPORT, result.actions)
        self.assertIn("제29조제1항제2호바목", " ".join(result.legal_basis))

    def test_facility_change_needs_cap_and_impact_facts(self):
        result = suggest_rule29_followup({
            "business_status": "영업허가",
            "facility_or_material_changed": "예",
        })
        self.assertFalse(result.actions)
        self.assertTrue(any("화학사고예방관리계획서" in q for q in result.questions))

    def test_facility_change_no_cap_submission_no_expansion_is_report(self):
        result = suggest_rule29_followup({
            "business_status": "영업허가",
            "facility_or_material_changed": "예",
            "cap_change_submission_required": "아니오",
            "overall_impact_expanded": "아니오",
            "scenario_quantity_or_more": "예",
        })
        self.assertIn(CHANGE_REPORT, result.actions)
        self.assertIn("제29조제1항제2호다목", " ".join(result.legal_basis))

    def test_permit_capacity_50pct_is_change_permission(self):
        result = suggest_rule29_followup({
            "business_status": "영업허가",
            "storage_or_transport_capacity_increased": "예",
            "cumulative_capacity_increase_50pct": "예",
        })
        self.assertIn(CHANGE_PERMISSION, result.actions)

    def test_declaration_capacity_50pct_is_change_report(self):
        result = suggest_rule29_followup({
            "business_status": "영업신고",
            "storage_or_transport_capacity_increased": "예",
            "cumulative_capacity_increase_50pct": "예",
        })
        self.assertEqual(result.actions, (CHANGE_REPORT,))
        self.assertIn("제29조제1항제3호나목", " ".join(result.legal_basis))

    def test_unknown_business_status_fails_closed(self):
        result = suggest_rule29_followup({"business_status": "미확인"})
        self.assertFalse(result.actions)
        self.assertTrue(result.questions)


if __name__ == "__main__":
    unittest.main()
