from __future__ import annotations

import unittest

import pandas as pd

from engine.cap_holding import calculate_facility_rows, compare_with_legal_rules
from engine.inventory import IntakeData


class CAPHoldingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intake = IntakeData(
            business={"사업장명": "테스트"},
            chemicals=pd.DataFrame(
                [
                    {
                        "제품명": "혼합물 A",
                        "CAS No.": "111-11-1",
                        "함량(%)": 30,
                        "취급형태": "사용+저장",
                        "수량 단위": "kg",
                    }
                ]
            ),
            documents={},
        )

    def test_volume_storage_and_exclusion_are_combined(self) -> None:
        facilities = pd.DataFrame(
            [
                {
                    "목록행번호": 1,
                    "시설명": "혼합조-1",
                    "시설유형": "제조·사용시설",
                    "제외시설여부": "N",
                    "제외사유": "해당없음",
                    "물질성상": "액체",
                    "공정유형": "변화없음",
                    "별표4 기준함량(%)": 30,
                    "설계용량": 1000,
                    "용량단위": "L",
                    "비중 또는 밀도(kg/L=ton/m3)": 1.2,
                    "질량단위": "kg",
                },
                {
                    "목록행번호": 1,
                    "시설명": "창고-1",
                    "시설유형": "보관시설",
                    "제외시설여부": "N",
                    "제외사유": "해당없음",
                    "물질성상": "액체",
                    "공정유형": "해당없음",
                    "별표4 기준함량(%)": 30,
                    "보관계획도 최대량": 5000,
                    "일일최대보관량": 7000,
                    "질량단위": "kg",
                },
                {
                    "목록행번호": 1,
                    "시설명": "탱크로리",
                    "시설유형": "저장탱크",
                    "제외시설여부": "Y",
                    "제외사유": "탱크로리·운송차량",
                    "물질성상": "액체",
                },
            ]
        )
        rows, blockers = calculate_facility_rows(self.intake, facilities)
        self.assertEqual(blockers, [])
        self.assertAlmostEqual(rows[0].max_holding_ton or 0.0, 1.2)
        self.assertAlmostEqual(rows[1].max_holding_ton or 0.0, 7.0)
        self.assertTrue(rows[2].excluded)

        legal = [
            {
                "source_key": "CAP_QTY_APP2",
                "row_no": 1,
                "cas": "111-11-1",
                "item_no": "10",
                "hazard_category": "급성",
                "content_threshold_pct": 25,
                "lowest_quantity_ton": 1,
                "lower_quantity_ton": 5,
                "upper_quantity_ton": 10,
            }
        ]
        comparison, compare_blockers = compare_with_legal_rules(rows, legal)
        self.assertEqual(compare_blockers, [])
        self.assertEqual(len(comparison), 1)
        self.assertAlmostEqual(comparison[0]["calculated_max_holding_ton"], 8.2)
        self.assertEqual(comparison[0]["quantity_band"], "하위 이상·상위 미만")

    def test_mixture_content_is_threshold_not_mass_multiplier(self) -> None:
        facilities = pd.DataFrame(
            [
                {
                    "목록행번호": 1,
                    "시설명": "탱크-1",
                    "시설유형": "저장탱크",
                    "제외시설여부": "N",
                    "제외사유": "해당없음",
                    "물질성상": "액체",
                    "공정유형": "해당없음",
                    "별표4 기준함량(%)": 30,
                    "설계용량": 10,
                    "용량단위": "m3",
                    "비중 또는 밀도(kg/L=ton/m3)": 1.1,
                }
            ]
        )
        rows, blockers = calculate_facility_rows(self.intake, facilities)
        self.assertEqual(blockers, [])
        self.assertAlmostEqual(rows[0].max_holding_ton or 0.0, 11.0)

    def test_gas_without_verified_mass_is_held(self) -> None:
        facilities = pd.DataFrame(
            [
                {
                    "목록행번호": 1,
                    "시설명": "가스설비",
                    "시설유형": "제조·사용시설",
                    "제외시설여부": "N",
                    "제외사유": "해당없음",
                    "물질성상": "기체·고압가스",
                    "공정유형": "변화없음",
                    "별표4 기준함량(%)": 30,
                }
            ]
        )
        rows, blockers = calculate_facility_rows(self.intake, facilities)
        self.assertEqual(len(rows), 1)
        self.assertTrue(blockers)
        self.assertIsNone(rows[0].max_holding_ton)


if __name__ == "__main__":
    unittest.main()
