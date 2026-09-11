import tempfile
import unittest
from pathlib import Path

import pandas as pd

from engine import cap_app1_engine
from engine.cap_sds_app1 import app1_sds_options, assess_sds_app1_row
from engine.inventory import IntakeData


class CAPSDSAppendix1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = cap_app1_engine.APPROVED_APP1_DB
        cap_app1_engine.APPROVED_APP1_DB = Path(self.tmp.name) / "cap_qty_app1.csv"
        pd.DataFrame(
            [
                {
                    "classification_system": "급성 유해성",
                    "hazard_group": "급성독성 (흡입)",
                    "category_no": 1,
                    "lower_quantity_ton": 1,
                    "upper_quantity_ton": 20,
                },
                {
                    "classification_system": "물리·화학적 위험성",
                    "hazard_group": "인화성 액체",
                    "category_no": 2,
                    "lower_quantity_ton": 5,
                    "upper_quantity_ton": 200,
                },
            ]
        ).to_csv(cap_app1_engine.APPROVED_APP1_DB, index=False)
        self.intake = IntakeData(
            business={"사업장명": "테스트"},
            chemicals=pd.DataFrame(
                [
                    {
                        "제품명": "테스트물질",
                        "CAS No.": "111-11-1",
                        "함량(%)": 100,
                        "취급형태": "저장",
                        "최대 동시보유량(알면 입력)": 1500,
                        "수량 단위": "kg",
                    }
                ]
            ),
            documents={},
        )

    def tearDown(self):
        cap_app1_engine.APPROVED_APP1_DB = self.old
        self.tmp.cleanup()

    def test_options_are_built_from_approved_db(self):
        options = app1_sds_options()
        self.assertEqual(len(options), 2)
        self.assertTrue(any(o.hazard_group == "급성독성 (흡입)" and o.category_no == 1 for o in options))

    def test_verified_no_app1_class_is_not_app1(self):
        result = assess_sds_app1_row(
            self.intake,
            1,
            [],
            verified_no_app1_class=True,
            holding_confirmed=False,
        )
        self.assertEqual(result.status, "NOT_APP1")

    def test_selected_sds_class_requires_holding_confirmation(self):
        option = next(o for o in app1_sds_options() if o.hazard_group == "급성독성 (흡입)")
        result = assess_sds_app1_row(
            self.intake,
            1,
            [option.key],
            holding_confirmed=False,
        )
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.lower_quantity_ton, 1)
        self.assertEqual(result.upper_quantity_ton, 20)

    def test_selected_sds_class_compares_confirmed_holding(self):
        option = next(o for o in app1_sds_options() if o.hazard_group == "급성독성 (흡입)")
        result = assess_sds_app1_row(
            self.intake,
            1,
            [option.key],
            holding_confirmed=True,
        )
        self.assertEqual(result.status, "LOWER_CANDIDATE")
        self.assertEqual(result.max_holding_ton, 1.5)
        self.assertEqual(result.lower_quantity_ton, 1)
        self.assertEqual(result.upper_quantity_ton, 20)

    def test_multiple_sds_classes_use_strictest_quantities(self):
        options = app1_sds_options()
        result = assess_sds_app1_row(
            self.intake,
            1,
            [o.key for o in options],
            holding_confirmed=True,
        )
        self.assertEqual(result.status, "LOWER_CANDIDATE")
        self.assertEqual(result.lower_quantity_ton, 1)
        self.assertEqual(result.upper_quantity_ton, 20)

    def test_conflicting_none_and_selected_holds(self):
        option = app1_sds_options()[0]
        result = assess_sds_app1_row(
            self.intake,
            1,
            [option.key],
            verified_no_app1_class=True,
            holding_confirmed=True,
        )
        self.assertEqual(result.status, "HOLD")
        self.assertTrue(result.blockers)


if __name__ == "__main__":
    unittest.main()
