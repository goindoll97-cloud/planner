from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from engine.inventory import IntakeData
from engine.psm_engine import PSMAssessment, PSMRatioLine
from engine.psm_followup import (
    PSMFollowupFacts,
    PSMNote8Adjustment,
    PSMPropertyAnswer,
    reassess_psm_with_followup,
)


class PSMFollowupIntegrationTests(unittest.TestCase):
    def test_ksic_20202_property_trigger_stays_candidate_even_when_r_below_one(self):
        db = pd.DataFrame(
            [
                {
                    "item_no": 1,
                    "substance_name": "인화성 가스",
                    "cas_list": "",
                    "match_type": "PROPERTY",
                    "manufacture_handling_threshold_kg": 5000.0,
                    "storage_threshold_kg": 200000.0,
                },
                {
                    "item_no": 2,
                    "substance_name": "인화성 액체",
                    "cas_list": "",
                    "match_type": "PROPERTY",
                    "manufacture_handling_threshold_kg": 5000.0,
                    "storage_threshold_kg": 200000.0,
                },
            ]
        )
        intake = IntakeData(
            business={"한국표준산업분류(KSIC) 코드": "20202"},
            chemicals=pd.DataFrame(),
            documents={},
        )
        base = PSMAssessment(
            status="ADDITIONAL_INFO_REQUIRED",
            label="PSM 대상업종 조건 확인 필요",
            db_ready=True,
            industry_code="20202",
            industry_match="합성수지 및 기타 플라스틱물질 제조업",
            r_value=0.0,
            blockers=["별표 13 제1호 인화성 가스 / 제2호 인화성 액체 여부 미확인"],
        )
        facts = PSMFollowupFacts(
            property_answers={
                1: PSMPropertyAnswer(True, 100.0, 0.0),
                2: PSMPropertyAnswer(False, 0.0, 0.0),
            }
        )
        with patch("engine.psm_followup._load_db", return_value=db):
            result = reassess_psm_with_followup(intake, facts, base)

        self.assertEqual(result.status, "APPLICABLE_CANDIDATE")
        self.assertTrue(result.industry_trigger)
        self.assertFalse(result.quantity_trigger)
        self.assertLess(result.r_value, 1.0)
        self.assertIn("INDUSTRY_TRIGGER", result.trigger_channels)

    def test_note8_adjustment_can_remove_quantity_trigger(self):
        db = pd.DataFrame(
            [
                {
                    "item_no": 3,
                    "substance_name": "가스 A",
                    "cas_list": "111-11-1",
                    "match_type": "CAS",
                    "manufacture_handling_threshold_kg": 1000.0,
                    "storage_threshold_kg": 1000.0,
                }
            ]
        )
        intake = IntakeData(business={}, chemicals=pd.DataFrame(), documents={})
        line = PSMRatioLine(
            legal_item_no=3,
            legal_substance="가스 A",
            source_rows="1",
            cas_values="111-11-1",
            manufacture_handling_kg=1200.0,
            storage_kg=0.0,
            manufacture_handling_threshold_kg=1000.0,
            storage_threshold_kg=1000.0,
            manufacture_handling_ratio=1.2,
            storage_ratio=0.0,
            controlling_ratio=1.2,
            controlling_basis="제조·취급",
            quantity_basis="test",
        )
        base = PSMAssessment(
            status="APPLICABLE_CANDIDATE",
            label="공정안전보고서 제출 대상 여부 확인 필요",
            db_ready=True,
            ratio_lines=[line],
            r_value=1.2,
        )
        facts = PSMFollowupFacts(
            note8_answer="YES",
            note8_exclusions={3: PSMNote8Adjustment(manufacture_handling_kg=400.0)},
        )
        with patch("engine.psm_followup._load_db", return_value=db):
            result = reassess_psm_with_followup(intake, facts, base)

        self.assertAlmostEqual(result.r_before_note8, 1.2)
        self.assertAlmostEqual(result.r_value, 0.8)
        self.assertFalse(result.quantity_trigger)
        self.assertEqual(result.status, "NO_TRIGGER_IN_CHECKED_SCOPE")

    def test_special_component_value_is_reinjected_into_r(self):
        db = pd.DataFrame(
            [
                {
                    "item_no": 23,
                    "substance_name": "발연황산",
                    "cas_list": "8014-95-7",
                    "match_type": "CAS",
                    "manufacture_handling_threshold_kg": 500.0,
                    "storage_threshold_kg": 500.0,
                }
            ]
        )
        intake = IntakeData(
            business={},
            chemicals=pd.DataFrame(
                [
                    {
                        "제품명": "발연황산",
                        "CAS No.": "8014-95-7",
                        "수량 단위": "kg",
                        "최대 제조·사용량": 600.0,
                        "최대 저장량": 0.0,
                    }
                ]
            ),
            documents={},
        )
        base = PSMAssessment(
            status="ADDITIONAL_INFO_REQUIRED",
            label="PSM 추가정보 필요",
            db_ready=True,
            r_value=0.0,
            blockers=["법정 농도·성분조건 미확인 항목: 23"],
        )
        facts = PSMFollowupFacts(special_values_pct={23: 70.0}, note8_answer="NO")
        with patch("engine.psm_followup._load_db", return_value=db):
            result = reassess_psm_with_followup(intake, facts, base)

        self.assertAlmostEqual(result.r_before_note8, 1.2)
        self.assertAlmostEqual(result.r_value, 1.2)
        self.assertTrue(result.quantity_trigger)
        self.assertEqual(result.status, "APPLICABLE_CANDIDATE")


if __name__ == "__main__":
    unittest.main()
