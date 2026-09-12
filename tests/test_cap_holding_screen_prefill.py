import unittest

import pandas as pd

from engine.cap_holding_screen import _app3_hits_for_row


class CAPHoldingScreenPrefillTests(unittest.TestCase):
    def setUp(self):
        self.app3 = pd.DataFrame(
            [
                {
                    "item_no": "42",
                    "substance_name": "테스트물질",
                    "cas_list": "111-11-1",
                    "variant_type": "BASE",
                    "content_threshold_pct": "10",
                    "lowest_quantity_ton": "0.1",
                    "lower_quantity_ton": "1",
                    "upper_quantity_ton": "10",
                },
                {
                    "item_no": "42",
                    "substance_name": "테스트물질(상온·상압 액체)",
                    "cas_list": "111-11-1",
                    "variant_type": "LIQUID_AT_AMBIENT",
                    "content_threshold_pct": "10",
                    "lowest_quantity_ton": "0.05",
                    "lower_quantity_ton": "0.5",
                    "upper_quantity_ton": "5",
                },
            ]
        )

    def test_yes_uses_liquid_variant(self):
        item = pd.Series(
            {
                "제품명": "테스트제품",
                "CAS No.": "111-11-1",
                "함량(%)": 35,
                "상온·상압 액체 여부(해당 시)": "Y",
            }
        )
        hits, blockers, claimed = _app3_hits_for_row(1, item, self.app3)
        self.assertTrue(claimed)
        self.assertEqual(blockers, [])
        self.assertEqual(hits[0]["variant_type"], "LIQUID_AT_AMBIENT")
        self.assertEqual(hits[0]["lower_quantity_ton"], 0.5)

    def test_no_uses_base_variant(self):
        item = pd.Series(
            {
                "제품명": "테스트제품",
                "CAS No.": "111-11-1",
                "함량(%)": 35,
                "상온·상압 액체 여부(해당 시)": "N",
            }
        )
        hits, blockers, claimed = _app3_hits_for_row(1, item, self.app3)
        self.assertTrue(claimed)
        self.assertEqual(blockers, [])
        self.assertEqual(hits[0]["variant_type"], "BASE")
        self.assertEqual(hits[0]["lower_quantity_ton"], 1.0)

    def test_missing_value_stays_hold(self):
        item = pd.Series(
            {
                "제품명": "테스트제품",
                "CAS No.": "111-11-1",
                "함량(%)": 35,
            }
        )
        hits, blockers, claimed = _app3_hits_for_row(1, item, self.app3)
        self.assertTrue(claimed)
        self.assertEqual(hits, [])
        self.assertTrue(any("상온·상압 액체 여부" in message for message in blockers))


if __name__ == "__main__":
    unittest.main()
