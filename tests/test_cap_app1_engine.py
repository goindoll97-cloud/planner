import tempfile
import unittest
from pathlib import Path

import pandas as pd

from engine import cap_app1_engine


class CAPAppendix1EngineTests(unittest.TestCase):
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
                {
                    "classification_system": "만성 유해성",
                    "hazard_group": "발암성물질 C",
                    "category_no": 1,
                    "lower_quantity_ton": 40,
                    "upper_quantity_ton": "",
                },
            ]
        ).to_csv(cap_app1_engine.APPROVED_APP1_DB, index=False)

    def tearDown(self):
        cap_app1_engine.APPROVED_APP1_DB = self.old
        self.tmp.cleanup()

    def test_priority_app3_over_app2_over_app1(self):
        self.assertEqual(
            cap_app1_engine.quantity_source_priority(appendix3_applies=True, appendix2_applies=True),
            "CAP_QTY_APP3",
        )
        self.assertEqual(
            cap_app1_engine.quantity_source_priority(appendix3_applies=False, appendix2_applies=True),
            "CAP_QTY_APP2",
        )
        self.assertEqual(
            cap_app1_engine.quantity_source_priority(appendix3_applies=False, appendix2_applies=False),
            "CAP_QTY_APP1",
        )

    def test_multiple_groups_use_smallest_applicable_quantities(self):
        result = cap_app1_engine.select_app1_quantities(
            [("급성독성 (흡입)", 1), ("인화성 액체", 2)]
        )
        self.assertTrue(result.ready)
        self.assertTrue(result.matched)
        self.assertEqual(result.lower_quantity_ton, 1)
        self.assertEqual(result.upper_quantity_ton, 20)

    def test_none_upper_does_not_replace_existing_upper(self):
        result = cap_app1_engine.select_app1_quantities(
            [("발암성물질 C", 1), ("인화성 액체", 2)]
        )
        self.assertEqual(result.lower_quantity_ton, 5)
        self.assertEqual(result.upper_quantity_ton, 200)


if __name__ == "__main__":
    unittest.main()
