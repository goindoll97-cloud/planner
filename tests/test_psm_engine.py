from __future__ import annotations

import unittest

from engine.psm_engine import (
    PSMRatioLine,
    _aggregate_ratio_lines,
    _legal_condition,
    calculate_r_value,
)


class PSMRValueTests(unittest.TestCase):
    def test_sum_of_controlling_ratios(self) -> None:
        lines = [
            PSMRatioLine(3, "A", "1", "1-11-1", 600, 0, 1000, 1000, 0.6, 0.0, 0.6, "제조·취급", "test"),
            PSMRatioLine(4, "B", "2", "2-22-2", 300, 0, 1000, 1000, 0.3, 0.0, 0.3, "제조·취급", "test"),
            PSMRatioLine(5, "C", "3", "3-33-3", 0, 200, 1000, 1000, 0.0, 0.2, 0.2, "저장", "test"),
        ]
        self.assertAlmostEqual(calculate_r_value(lines), 1.1, places=8)

    def test_same_legal_item_is_aggregated_before_ratio(self) -> None:
        contributions = [
            {
                "company_row": 1,
                "cas": "624-83-9",
                "item_no": 3,
                "legal_substance": "메틸 이소시아네이트",
                "mfg_kg": 400.0,
                "storage_kg": None,
                "mfg_threshold": 1000.0,
                "storage_threshold": 1000.0,
                "quantity_basis": "순도 100%",
            },
            {
                "company_row": 2,
                "cas": "624-83-9",
                "item_no": 3,
                "legal_substance": "메틸 이소시아네이트",
                "mfg_kg": 700.0,
                "storage_kg": None,
                "mfg_threshold": 1000.0,
                "storage_threshold": 1000.0,
                "quantity_basis": "순도 100%",
            },
        ]
        lines = _aggregate_ratio_lines(contributions)
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(lines[0].manufacture_handling_kg, 1100.0)
        self.assertAlmostEqual(lines[0].controlling_ratio, 1.1)

    def test_item1_uses_separate_storage_threshold(self) -> None:
        contributions = [
            {
                "company_row": 1,
                "cas": "PROPERTY",
                "item_no": 1,
                "legal_substance": "인화성 가스",
                "mfg_kg": 2500.0,
                "storage_kg": 150000.0,
                "mfg_threshold": 5000.0,
                "storage_threshold": 200000.0,
                "quantity_basis": "property test",
            }
        ]
        line = _aggregate_ratio_lines(contributions)[0]
        self.assertAlmostEqual(line.manufacture_handling_ratio, 0.5)
        self.assertAlmostEqual(line.storage_ratio, 0.75)
        self.assertAlmostEqual(line.controlling_ratio, 0.75)
        self.assertEqual(line.controlling_basis, "저장")


class PSMConcentrationTests(unittest.TestCase):
    def test_ordinary_row_uses_purity_equivalent_mass(self) -> None:
        legal = {"item_no": 3, "substance_name": "메틸 이소시아네이트"}
        applicable, factor, _, question = _legal_condition(legal, 50, "제품A", "624-83-9")
        self.assertTrue(applicable)
        self.assertAlmostEqual(factor, 0.5)
        self.assertEqual(question, "")

    def test_concentration_defined_row_uses_product_mass_when_condition_met(self) -> None:
        legal = {"item_no": 48, "substance_name": "불산(중량 10% 이상)"}
        applicable, factor, _, question = _legal_condition(legal, 20, "불산제품", "7664-39-3")
        self.assertTrue(applicable)
        self.assertEqual(factor, 1.0)
        self.assertEqual(question, "")

    def test_concentration_defined_row_is_not_applicable_below_threshold(self) -> None:
        legal = {"item_no": 48, "substance_name": "불산(중량 10% 이상)"}
        applicable, factor, _, _ = _legal_condition(legal, 5, "불산제품", "7664-39-3")
        self.assertFalse(applicable)
        self.assertIsNone(factor)

    def test_special_component_condition_is_held_for_followup(self) -> None:
        legal = {"item_no": 23, "substance_name": "발연황산(삼산화황 중량 65% 이상 80% 미만)"}
        applicable, factor, _, question = _legal_condition(legal, 70, "발연황산", "8014-95-7")
        self.assertIsNone(applicable)
        self.assertIsNone(factor)
        self.assertIn("삼산화황", question)


if __name__ == "__main__":
    unittest.main()
