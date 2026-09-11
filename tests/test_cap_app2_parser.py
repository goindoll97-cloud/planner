import unittest

import pandas as pd

from engine.cap_app2_parser import _anchor_checks


class CAPAppendix2AnchorTests(unittest.TestCase):
    def test_solution_rows_are_found_by_category_not_fixed_sequence(self):
        rows = [
            {
                "item_no": 282,
                "hazard_seq": 1,
                "hazard_category": "급성",
                "content_threshold_pct": 10.0,
                "lowest_quantity_ton": 0.05,
                "lower_quantity_ton": 2.0,
                "upper_quantity_ton": 40.0,
                "direct_cas": "7664-41-7",
                "scope_type": "DIRECT_CAS",
                "all_cas_in_row": "7664-41-7",
                "cas_list": "7664-41-7",
            },
            {
                "item_no": 282,
                "hazard_seq": 2,
                "hazard_category": "생태",
                "content_threshold_pct": 25.0,
                "lowest_quantity_ton": 0.05,
                "lower_quantity_ton": 2.0,
                "upper_quantity_ton": 40.0,
                "direct_cas": "7664-41-7",
                "scope_type": "DIRECT_CAS",
                "all_cas_in_row": "7664-41-7",
                "cas_list": "7664-41-7",
            },
            {
                "item_no": 282,
                "hazard_seq": 3,
                "hazard_category": "용액",
                "content_threshold_pct": None,
                "lowest_quantity_ton": 0.5,
                "lower_quantity_ton": 20.0,
                "upper_quantity_ton": 400.0,
                "direct_cas": "7664-41-7",
                "scope_type": "DIRECT_CAS",
                "all_cas_in_row": "7664-41-7",
                "cas_list": "7664-41-7",
            },
            {
                "item_no": 557,
                "hazard_seq": 1,
                "hazard_category": "급성",
                "content_threshold_pct": 1.0,
                "lowest_quantity_ton": 0.01,
                "lower_quantity_ton": 0.4,
                "upper_quantity_ton": 2.0,
                "direct_cas": "7664-39-3",
                "scope_type": "DIRECT_CAS",
                "all_cas_in_row": "7664-39-3",
                "cas_list": "7664-39-3",
            },
            {
                "item_no": 557,
                "hazard_seq": 2,
                "hazard_category": "용액",
                "content_threshold_pct": None,
                "lowest_quantity_ton": 0.1,
                "lower_quantity_ton": 4.0,
                "upper_quantity_ton": 20.0,
                "direct_cas": "7664-39-3",
                "scope_type": "DIRECT_CAS",
                "all_cas_in_row": "7664-39-3",
                "cas_list": "7664-39-3",
            },
        ]
        checks = _anchor_checks(pd.DataFrame(rows))
        self.assertTrue(checks["item282_solution_variant"])
        self.assertTrue(checks["item557_solution_variant"])


if __name__ == "__main__":
    unittest.main()
