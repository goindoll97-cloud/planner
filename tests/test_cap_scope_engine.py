import unittest

import pandas as pd

from engine.cap_scope_engine import (
    screen_cap_direct_from_tables,
    screen_cap_scope_candidates_from_tables,
)
from engine.inventory import IntakeData


class CAPScopeEngineTest(unittest.TestCase):
    def _intake(
        self,
        cas: str,
        name: str = "시험물질",
        concentration: float = 20,
        holding_kg: float = 10,
    ) -> IntakeData:
        chemicals = pd.DataFrame([
            {
                "No.": 1,
                "제품명": name,
                "CAS No.": cas,
                "물질명(알면 입력)": name,
                "함량(%)": concentration,
                "취급형태": "사용",
                "최대 제조·사용량": 10,
                "최대 저장량": 10,
                "수량 단위": "kg",
                "최대 동시보유량(알면 입력)": holding_kg,
            }
        ])
        return IntakeData(business={}, chemicals=chemicals, documents={})

    def test_embedded_component_cas_is_review_candidate(self):
        table = pd.DataFrame([
            {
                "designation_id": "APP2-GROUP-1",
                "scope_type": "REACTION_PRODUCT",
                "direct_cas": "",
                "substance_name": "반응생성물",
                "source_text": "A와 B의 반응생성물. 구성성분 32588-54-8 포함",
                "all_cas_in_row": "32588-54-8",
                "content_threshold_pct": "1",
                "active": "True",
            }
        ])
        found = screen_cap_scope_candidates_from_tables(
            self._intake("32588-54-8"), {"CAP_QTY_APP2": table}
        )
        self.assertFalse(found.empty)
        self.assertIn("COMPONENT_CAS_CANDIDATE", set(found["candidate_match_type"]))
        self.assertTrue((found["candidate_status"] == "판정보류(포괄 규제범위 확인 필요)").all())

    def test_direct_cas_row_is_not_reprocessed_as_broad_scope(self):
        table = pd.DataFrame([
            {
                "designation_id": "APP2-DIRECT-1",
                "scope_type": "DIRECT_CAS",
                "direct_cas": "32588-54-8",
                "substance_name": "직접지정물질",
                "source_text": "직접 CAS 지정",
                "active": "True",
            }
        ])
        found = screen_cap_scope_candidates_from_tables(
            self._intake("32588-54-8"), {"CAP_QTY_APP2": table}
        )
        self.assertTrue(found.empty)

    def test_broad_salt_parent_cas_uses_direct_path_not_duplicate_scope_candidate(self):
        table = pd.DataFrame([
            {
                "designation_id": "APP2-SALT-1",
                "scope_type": "SALT_FAMILY",
                "direct_cas": "7803-49-8",
                "cas_list": "7803-49-8",
                "all_cas_in_row": "7803-49-8",
                "substance_name": "히드록실아민 및 그 염류",
                "source_text": "히드록실아민(7803-49-8) 및 그 염류",
                "hazard_category": "인체급성유해성",
                "content_threshold_pct": "1",
                "lowest_quantity_ton": "0.1",
                "lower_quantity_ton": "1",
                "upper_quantity_ton": "10",
                "active": "True",
            }
        ])
        intake = self._intake("7803-49-8", "Hydroxylamine", concentration=20, holding_kg=2000)
        broad = screen_cap_scope_candidates_from_tables(intake, {"CAP_QTY_APP2": table})
        direct, questions, blockers = screen_cap_direct_from_tables(intake, {"CAP_QTY_APP2": table})
        self.assertTrue(broad.empty)
        self.assertFalse(direct.empty)
        self.assertIn("하위 이상·상위 미만", set(direct["quantity_band"]))
        self.assertEqual(questions, [])
        self.assertEqual(blockers, [])

    def test_exact_direct_cas_applies_concentration_and_quantity(self):
        table = pd.DataFrame([
            {
                "record_key": "1:1",
                "item_no": "1",
                "designation_id": "APP2-DIRECT-1",
                "scope_type": "DIRECT_CAS",
                "direct_cas": "1313-60-6",
                "substance_name": "과산화나트륨",
                "hazard_category": "인체급성유해성",
                "content_threshold_pct": "10",
                "lowest_quantity_ton": "0.125",
                "lower_quantity_ton": "5",
                "upper_quantity_ton": "200",
                "active": "True",
            }
        ])
        intake = self._intake("1313-60-6", "과산화나트륨", concentration=20, holding_kg=6000)
        direct, questions, blockers = screen_cap_direct_from_tables(intake, {"CAP_QTY_APP2": table})
        self.assertEqual(len(direct), 1)
        self.assertEqual(direct.iloc[0]["quantity_band"], "하위 이상·상위 미만")
        self.assertEqual(questions, [])
        self.assertEqual(blockers, [])

    def test_solution_variant_is_held_for_condition_confirmation(self):
        table = pd.DataFrame([
            {
                "record_key": "282:1",
                "item_no": "282",
                "designation_id": "APP2-NH3",
                "scope_type": "DIRECT_CAS",
                "direct_cas": "7664-41-7",
                "substance_name": "암모니아",
                "hazard_category": "인체급성유해성",
                "content_threshold_pct": "25",
                "lowest_quantity_ton": "0.05",
                "lower_quantity_ton": "2",
                "upper_quantity_ton": "40",
                "active": "True",
            },
            {
                "record_key": "282:2",
                "item_no": "282",
                "designation_id": "APP2-NH3",
                "scope_type": "DIRECT_CAS",
                "direct_cas": "7664-41-7",
                "substance_name": "암모니아",
                "hazard_category": "용액",
                "content_threshold_pct": "",
                "lowest_quantity_ton": "0.5",
                "lower_quantity_ton": "20",
                "upper_quantity_ton": "400",
                "active": "True",
            },
        ])
        direct, questions, blockers = screen_cap_direct_from_tables(
            self._intake("7664-41-7", "암모니아", concentration=30, holding_kg=3000),
            {"CAP_QTY_APP2": table},
        )
        self.assertTrue(direct.empty)
        self.assertTrue(any("용액" in q for q in questions))
        self.assertTrue(any("용액 특수조건" in b for b in blockers))

    def test_explicit_exception_has_priority_candidate_type(self):
        table = pd.DataFrame([
            {
                "designation_id": "APP2-GROUP-EX",
                "scope_type": "COMPOUND_GROUP",
                "direct_cas": "",
                "substance_name": "Toluenediamines",
                "source_text": "Toluenediamines excluding 2,6-toluenediamine (823-40-5)",
                "exception_cas": "823-40-5",
                "active": "True",
            }
        ])
        found = screen_cap_scope_candidates_from_tables(
            self._intake("823-40-5", "2,6-Toluenediamine"), {"CAP_QTY_APP2": table}
        )
        self.assertFalse(found.empty)
        self.assertIn("EXPLICIT_EXCEPTION_CAS", set(found["candidate_match_type"]))


if __name__ == "__main__":
    unittest.main()
