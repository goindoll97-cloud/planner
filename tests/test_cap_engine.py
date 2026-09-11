from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from engine import cap_engine
from engine.inventory import IntakeData


class CAPEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = cap_engine.APPROVED_CAP3_DB
        cap_engine.APPROVED_CAP3_DB = Path(self.tmp.name) / "cap_qty_app3.csv"
        pd.DataFrame(
            [
                {
                    "record_key": "10",
                    "item_no": 10,
                    "variant_type": "BASE",
                    "substance_name": "시험 사고대비물질",
                    "cas_list": "123-45-6",
                    "content_threshold_pct": 10.0,
                    "lowest_quantity_ton": 0.05,
                    "lower_quantity_ton": 0.2,
                    "upper_quantity_ton": 1.0,
                }
            ]
        ).to_csv(cap_engine.APPROVED_CAP3_DB, index=False)

    def tearDown(self):
        cap_engine.APPROVED_CAP3_DB = self.old_path
        self.tmp.cleanup()

    def _intake(self, holding_kg=300.0, pct=100.0):
        return IntakeData(
            business={"사업장명": "테스트", "사업장 주소": "테스트", "업종 또는 주요 생산품": "테스트"},
            chemicals=pd.DataFrame(
                [
                    {
                        "제품명": "시험물질",
                        "CAS No.": "123-45-6",
                        "함량(%)": pct,
                        "취급형태": "사용",
                        "최대 제조·사용량": 0,
                        "최대 저장량": 0,
                        "수량 단위": "kg",
                        "최대 동시보유량(알면 입력)": holding_kg,
                    }
                ]
            ),
            documents={},
        )

    def test_lower_band_from_max_simultaneous_holding(self):
        result = cap_engine.assess_cap(self._intake(holding_kg=300.0))
        self.assertEqual(result.status, "APP3_LOWER_CANDIDATE")
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0].quantity_band, "하위 이상·상위 미만")
        self.assertAlmostEqual(result.hits[0].max_holding_ton, 0.3)

    def test_below_content_threshold_is_not_counted(self):
        result = cap_engine.assess_cap(self._intake(holding_kg=300.0, pct=5.0))
        self.assertEqual(result.status, "APP3_NO_CONFIRMED_MATCH")
        self.assertEqual(result.hits, [])

    def test_missing_max_holding_creates_followup(self):
        intake = self._intake()
        intake.chemicals.loc[0, "최대 동시보유량(알면 입력)"] = None
        result = cap_engine.assess_cap(intake)
        self.assertTrue(any("최대 동시보유량" in q for q in result.questions))
        self.assertTrue(any("최대보유량 미확인" in b for b in result.blockers))


if __name__ == "__main__":
    unittest.main()
