from __future__ import annotations

import unittest

import pandas as pd

from engine.psm_followup import (
    PSMFollowupFacts,
    PSMNote8Adjustment,
    PSMPropertyAnswer,
    _property_lines,
    _special_condition_applies,
    apply_note8_exclusions,
)
from engine.psm_engine import PSMRatioLine, calculate_r_value


class PSMFollowupPropertyTests(unittest.TestCase):
    def test_property_item1_recalculates_with_separate_storage_threshold(self):
        db = pd.DataFrame(
            [
                {
                    "item_no": 1,
                    "substance_name": "인화성 가스",
                    "match_type": "PROPERTY",
                    "manufacture_handling_threshold_kg": 5000.0,
                    "storage_threshold_kg": 200000.0,
                }
            ]
        )
        facts = PSMFollowupFacts(
            property_answers={
                1: PSMPropertyAnswer(
                    applicable=True,
                    manufacture_handling_kg=2500.0,
                    storage_kg=150000.0,
                )
            }
        )
        lines, blockers = _property_lines(db, facts, (1,))
        self.assertEqual(blockers, [])
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(lines[0].manufacture_handling_ratio, 0.5)
        self.assertAlmostEqual(lines[0].storage_ratio, 0.75)
        self.assertAlmostEqual(lines[0].controlling_ratio, 0.75)

    def test_property_yes_requires_both_quantity_fields(self):
        db = pd.DataFrame(
            [
                {
                    "item_no": 2,
                    "substance_name": "인화성 액체",
                    "match_type": "PROPERTY",
                    "manufacture_handling_threshold_kg": 5000.0,
                    "storage_threshold_kg": 200000.0,
                }
            ]
        )
        facts = PSMFollowupFacts(
            property_answers={2: PSMPropertyAnswer(applicable=True, manufacture_handling_kg=100.0)}
        )
        lines, blockers = _property_lines(db, facts, (2,))
        self.assertEqual(lines, [])
        self.assertTrue(any("모두 kg로 확인" in value for value in blockers))


class PSMSpecialConditionTests(unittest.TestCase):
    def test_fuming_sulfuric_acid_range(self):
        self.assertTrue(_special_condition_applies(23, 65.0))
        self.assertTrue(_special_condition_applies(23, 79.9))
        self.assertFalse(_special_condition_applies(23, 80.0))
        self.assertFalse(_special_condition_applies(23, 64.9))

    def test_nitrocellulose_nitrogen_threshold(self):
        self.assertFalse(_special_condition_applies(42, 12.5))
        self.assertTrue(_special_condition_applies(42, 12.6))


class PSMNote8Tests(unittest.TestCase):
    def _line(self) -> PSMRatioLine:
        return PSMRatioLine(
            legal_item_no=3,
            legal_substance="가스 A",
            source_rows="1",
            cas_values="1-11-1",
            manufacture_handling_kg=1200.0,
            storage_kg=0.0,
            manufacture_handling_threshold_kg=1000.0,
            storage_threshold_kg=1000.0,
            manufacture_handling_ratio=1.2,
            storage_ratio=0.0,
            controlling_ratio=1.2,
            controlling_basis="제조·취급",
            quantity_basis="test",
        )

    def test_note8_exclusion_reduces_r(self):
        lines, blockers = apply_note8_exclusions(
            [self._line()],
            {3: PSMNote8Adjustment(manufacture_handling_kg=400.0, storage_kg=0.0)},
        )
        self.assertEqual(blockers, [])
        self.assertAlmostEqual(lines[0].manufacture_handling_kg, 800.0)
        self.assertAlmostEqual(calculate_r_value(lines), 0.8)

    def test_note8_exclusion_cannot_exceed_current_quantity(self):
        _, blockers = apply_note8_exclusions(
            [self._line()],
            {3: PSMNote8Adjustment(manufacture_handling_kg=1300.0, storage_kg=0.0)},
        )
        self.assertTrue(any("현재 계산수량보다 큽니다" in value for value in blockers))


if __name__ == "__main__":
    unittest.main()
