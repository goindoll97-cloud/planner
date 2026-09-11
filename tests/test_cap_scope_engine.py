import unittest

import pandas as pd

from engine.cap_scope_engine import screen_cap_scope_candidates_from_tables
from engine.inventory import IntakeData


class CAPScopeEngineTest(unittest.TestCase):
    def _intake(self, cas: str, name: str = "시험물질") -> IntakeData:
        chemicals = pd.DataFrame([
            {
                "No.": 1,
                "제품명": name,
                "CAS No.": cas,
                "물질명(알면 입력)": name,
                "함량(%)": 20,
                "취급형태": "사용",
                "최대 제조·사용량": 10,
                "최대 저장량": 10,
                "수량 단위": "kg",
                "최대 동시보유량(알면 입력)": 10,
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
                "content_threshold_pct": "1",
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
            }
        ])
        found = screen_cap_scope_candidates_from_tables(
            self._intake("32588-54-8"), {"CAP_QTY_APP2": table}
        )
        self.assertTrue(found.empty)

    def test_explicit_exception_has_priority_candidate_type(self):
        table = pd.DataFrame([
            {
                "designation_id": "APP2-GROUP-EX",
                "scope_type": "COMPOUND_GROUP",
                "direct_cas": "",
                "substance_name": "Toluenediamines",
                "source_text": "Toluenediamines excluding 2,6-toluenediamine (823-40-5)",
                "exception_cas": "823-40-5",
            }
        ])
        found = screen_cap_scope_candidates_from_tables(
            self._intake("823-40-5", "2,6-Toluenediamine"), {"CAP_QTY_APP2": table}
        )
        self.assertFalse(found.empty)
        self.assertIn("EXPLICIT_EXCEPTION_CAS", set(found["candidate_match_type"]))


if __name__ == "__main__":
    unittest.main()
