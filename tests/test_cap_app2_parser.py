from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from engine.cap_app2_parser import _anchor_checks, _solution_note_item_numbers


class CAPAppendix2AnchorTests(unittest.TestCase):
    def test_solution_rows_are_found_by_category_not_fixed_sequence(self):
        rows = [
            {
                "item_no": 283,
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
                "item_no": 283,
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
                "item_no": 283,
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
                "item_no": 558,
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
                "item_no": 558,
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
        self.assertTrue(checks["ammonia_solution_variant"])
        self.assertTrue(checks["hydrogen_fluoride_solution_variant"])

    def test_solution_note_item_numbers_are_read_from_first_page(self):
        class FakePage:
            def extract_text(self):
                return "표의 제282호, 제557호의 물질은 용액 구분에 따라 적용한다."

        class FakePdf:
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("engine.cap_app2_parser.pdfplumber.open", return_value=FakePdf()):
            self.assertEqual(_solution_note_item_numbers(Path("x.pdf")), [282, 557])

    def test_solution_note_unreadable_pdf_gives_no_numbers(self):
        with patch("engine.cap_app2_parser.pdfplumber.open", side_effect=OSError("bad")):
            self.assertEqual(_solution_note_item_numbers(Path("x.pdf")), [])


if __name__ == "__main__":
    unittest.main()
