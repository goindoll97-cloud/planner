from __future__ import annotations

import unittest

from engine.cap_app4_parser import EXPECTED_CORE_RULE_IDS, _anchor_checks, _parse_core_rules


SAMPLE = """
[별표 4] 최대보유량 산정 방법
1. 유해화학물질별 최대보유량 산정은 사업장 내에서 해당 유해화학물질을 취급하는 모든 제조·사용시설 및 저장·보관시설에서 해당 물질이 어느 순간 최대로 체류할 수 있는 양의 합으로 산정한다. 또한 취급시설별 최대보유량(탱크로리 등 운송·운반차량, 사외배관, 취급중단을 신고한 시설은 제외)은 취급시설의 설계용량과 비중을 고려한다.
2. 제조·사용시설의 경우
가. 제조·사용시설에서 유해화학물질이 함량기준 이상으로 존재하는 경우 취급시설의 설계용량과 유해화학물질의 비중을 고려하여 산정한다. 다만 단순 혼합의 경우 투입완료 후 최종함량을 기준으로 산정하고, 투입 후 반응이 일어나는 경우 반응이 일어나기 전 최종함량을 기준으로 산정한다.
나. 탑조류 또는 냉각기 등 서로 다른 물질의 성상이 두 개 이상 존재하여 사업장에서 근거를 들어 증빙하는 경우 각각의 성상이 차지하는 부피를 고려할 수 있다. 증빙이 불가능한 경우 설계용량과 액상의 비중을 이용한다.
3. 저장·보관시설의 경우
가. 저장탱크의 경우 저장탱크의 설계용량과 유해화학물질의 상온에서의 비중값을 이용하여 산정한다.
나. 보관시설의 경우 유해화학물질의 보관 계획도를 기준으로 최대보유량을 산정한다. 다만 보관시설의 일일최대보관량을 고려하여 일일최대보관량 이상으로 산정하여야 한다.
다. 나목에도 불구하고 유해화학물질 보관시설만을 설치·운영하는 사업장의 모든 보관물질의 최대보유량이 최하위 규정수량 미만인 경우에는 별도 기준을 적용한다.
※ 비 고
1. 기상물질의 경우 제조·사용시설의 운전조건을 고려하고 고압가스의 저장 방식을 고려한다.
2. 혼합물의 경우 규제대상 함량 이상의 유해화학물질을 모두 고려한다.
"""


class CAPAppendix4ParserTests(unittest.TestCase):
    def test_core_rule_ids_are_stable(self) -> None:
        rows = _parse_core_rules(SAMPLE)
        self.assertEqual([row["rule_id"] for row in rows], EXPECTED_CORE_RULE_IDS)
        self.assertTrue(all(row["rule_text"] for row in rows))

    def test_current_semantic_anchors(self) -> None:
        rows = _parse_core_rules(SAMPLE)
        checks = _anchor_checks(SAMPLE, rows)
        self.assertTrue(all(checks.values()), checks)


if __name__ == "__main__":
    unittest.main()
