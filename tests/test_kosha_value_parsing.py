from __future__ import annotations

import unittest

from engine.stage2 import cap_authoritative as auth


def _payload(items9=(), items8=()):
    return {"sections": {"9": {"items": [list(i) for i in items9]}, "8": {"items": [list(i) for i in items8]}}}


class KoshaValueParsingTests(unittest.TestCase):
    def test_explosion_range_is_split_using_the_order_in_the_label(self):
        payload = _payload([("인화 또는 폭발 범위의 상한/하한", "7.8 / 1.0 %  |   ※출처 : GESTIS")])
        self.assertEqual(auth._explosion_limits(payload)[:2], ("1.0", "7.8"))
        reversed_label = _payload([("폭발 범위(하한/상한)", "1.0 - 7.8 %")])
        self.assertEqual(auth._explosion_limits(reversed_label)[:2], ("1.0", "7.8"))

    def test_explosion_range_is_not_guessed_without_an_order_or_a_number(self):
        self.assertIsNone(auth._explosion_limits(_payload([("폭발 범위", "7.8 / 1.0 %")])))
        self.assertIsNone(auth._explosion_limits(_payload([("인화 또는 폭발 범위의 상한/하한", "자료없음")])))

    def test_source_tail_is_removed_from_values(self):
        self.assertEqual(auth._without_source_tail("액체   |   ※출처 : HSDB"), "액체")
        self.assertEqual(auth._without_source_tail("0.8623 (g/cu cm at 20℃)|   ※출처 : HSDB"), "0.8623 (g/cu cm at 20℃)")

    def test_header_rows_are_not_values(self):
        payload = _payload(items8=[("화학물질의 노출기준, 생물학적 노출기준 등", "1 | H02 | 화학물질의 노출기준 | 1142 | H"),
                                   ("국내규정", "|TWA : 50ppm |STEL : 150ppm(허용기준)")])
        self.assertEqual(auth._first_explicit(payload, (8,), ("TWA", "시간가중평균"))[0], "50ppm")


if __name__ == "__main__":
    unittest.main()
