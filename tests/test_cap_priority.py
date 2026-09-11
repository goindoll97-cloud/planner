import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from engine import cap_engine
from engine.cap_scope_engine import CAPScopeScreen
from engine.inventory import IntakeData


class CAPQuantityPriorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cap3 = cap_engine.APPROVED_CAP3_DB
        cap_engine.APPROVED_CAP3_DB = Path(self.tmp.name) / "cap_qty_app3.csv"
        pd.DataFrame([
            {
                "record_key": "1",
                "item_no": 1,
                "variant_type": "BASE",
                "substance_name": "우선순위 시험물질",
                "cas_list": "123-45-6",
                "content_threshold_pct": 1,
                "lowest_quantity_ton": 0.05,
                "lower_quantity_ton": 0.2,
                "upper_quantity_ton": 1.0,
            }
        ]).to_csv(cap_engine.APPROVED_CAP3_DB, index=False)

    def tearDown(self):
        cap_engine.APPROVED_CAP3_DB = self.old_cap3
        self.tmp.cleanup()

    def _intake(self):
        return IntakeData(
            business={"사업장명": "시험", "사업장 주소": "시험", "업종 또는 주요 생산품": "시험"},
            chemicals=pd.DataFrame([
                {
                    "제품명": "시험물질",
                    "CAS No.": "123-45-6",
                    "함량(%)": 100,
                    "취급형태": "사용",
                    "최대 제조·사용량": 0,
                    "최대 저장량": 0,
                    "수량 단위": "kg",
                    "최대 동시보유량(알면 입력)": 500,
                }
            ]),
            documents={},
        )

    def test_appendix3_prevents_appendix2_override(self):
        fake_scope = CAPScopeScreen(
            ready_keys=["CAP_QTY_APP2"],
            direct_hits=[
                {
                    "source_key": "CAP_QTY_APP2",
                    "row_no": 1,
                    "cas": "123-45-6",
                    "quantity_band": "상위 규정수량 이상",
                }
            ],
        )
        with patch.object(cap_engine, "assess_cap_scope", return_value=fake_scope), patch.object(
            cap_engine, "load_approved_app1", return_value=pd.DataFrame([{"ok": 1}])
        ):
            result = cap_engine.assess_cap(self._intake())

        self.assertEqual(result.status, "LOWER_CANDIDATE")
        self.assertEqual(result.scope_direct_hits, [])
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0].quantity_band, "하위 이상·상위 미만")


if __name__ == "__main__":
    unittest.main()
