from __future__ import annotations

import unittest

import pandas as pd

from engine.cap_quick_holding import compare_confirmed_declared_holding
from engine.inventory import IntakeData


class CAPQuickHoldingTests(unittest.TestCase):
    def test_phosgene_300kg_hits_lower_threshold(self) -> None:
        intake = IntakeData(
            business={"사업장명": "test"},
            chemicals=pd.DataFrame(
                [
                    {
                        "제품명": "포스겐",
                        "CAS No.": "75-44-5",
                        "함량(%)": 100,
                        "수량 단위": "kg",
                        "최대 동시보유량(알면 입력)": 300,
                    }
                ]
            ),
            documents={},
        )
        legal_hits = [
            {
                "source_key": "CAP_QTY_APP3",
                "row_no": 1,
                "item_no": "12",
                "legal_substance": "포스겐[Phosgene]",
                "lowest_quantity_ton": 0.005,
                "lower_quantity_ton": 0.3,
                "upper_quantity_ton": 1.5,
            }
        ]
        result = compare_confirmed_declared_holding(intake, legal_hits)
        self.assertEqual(result.status, "LOWER_CANDIDATE")
        self.assertEqual(result.comparison_rows[0]["quantity_band"], "하위 이상·상위 미만")
        self.assertEqual(result.comparison_rows[0]["confirmed_max_holding_ton"], 0.3)

    def test_missing_mass_unit_holds(self) -> None:
        intake = IntakeData(
            business={"사업장명": "test"},
            chemicals=pd.DataFrame(
                [
                    {
                        "제품명": "X",
                        "CAS No.": "1-11-1",
                        "수량 단위": "L",
                        "최대 동시보유량(알면 입력)": 100,
                    }
                ]
            ),
            documents={},
        )
        legal_hits = [
            {
                "source_key": "CAP_QTY_APP2",
                "row_no": 1,
                "item_no": "1",
                "lower_quantity_ton": 1,
                "upper_quantity_ton": 10,
            }
        ]
        result = compare_confirmed_declared_holding(intake, legal_hits)
        self.assertEqual(result.status, "HOLD")
        self.assertTrue(result.blockers)


if __name__ == "__main__":
    unittest.main()
