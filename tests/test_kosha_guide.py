from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from engine import kosha_guide as kg
from engine.stage2 import cap_basis_guides as basis


def _body(items, code="00", total=None):
    return json.dumps({"response": {"header": {"resultCode": code, "resultMsg": "NORMAL_CODE"},
                                    "body": {"pageNo": 1, "totalCount": total or len(items), "numOfRows": 10,
                                             "items": {"item": items} if items else ""}}})


P92 = [
    {"techGdlnNm": "누출원 모델링에 관한 기술지침", "techGdlnNo": "P-92-2012", "techGdlnOfancYmd": "2012-07-30",
     "fileDownloadUrl": "https://portal.kosha.or.kr/openapi/v1/file/down/a"},
    {"techGdlnNm": "누출원 모델링에 관한 기술지침", "techGdlnNo": "P-92-2023", "techGdlnOfancYmd": "2023-08-24",
     "fileDownloadUrl": "https://portal.kosha.or.kr/openapi/v1/file/down/b"},
    {"techGdlnNm": "다른 지침", "techGdlnNo": "P-9-2020", "techGdlnOfancYmd": "2020-01-01", "fileDownloadUrl": ""},
]


class GuideClientTests(unittest.TestCase):
    def test_no_key_means_no_call(self):
        calls = []
        with patch("engine.kosha_guide._credential", return_value=""):
            result = kg.search_guides(number="P-92", get=lambda url, params: calls.append(url) or (200, ""))
        self.assertEqual(result.status, "NOT_CONFIGURED")
        self.assertEqual(calls, [])

    def test_request_follows_the_open_api_guide(self):
        seen = {}

        def fake(url, params):
            seen.update(url=url, params=params)
            return 200, _body(P92)

        with patch("engine.kosha_guide._credential", return_value="KEY"):
            result = kg.search_guides(number="P-92", get=fake)
        self.assertEqual(seen["url"], "https://apis.data.go.kr/B552468/koshaguide/getKoshaGuide")
        self.assertEqual(seen["params"]["callApiId"], "1050")
        self.assertEqual(seen["params"]["techGdlnNo"], "P-92")
        self.assertEqual(seen["params"]["serviceKey"], "KEY")
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.items[1].download_url, "https://portal.kosha.or.kr/openapi/v1/file/down/b")

    def test_latest_version_picks_the_newest_year_of_the_exact_guide(self):
        with patch("engine.kosha_guide._credential", return_value="KEY"):
            latest, result = kg.latest_version("P-92", get=lambda u, p: (200, _body(P92)))
        self.assertEqual(latest.number, "P-92-2023")  # P-9-2020은 다른 지침
        self.assertEqual(latest.year, 2023)

    def test_single_item_object_and_empty_results_are_handled(self):
        with patch("engine.kosha_guide._credential", return_value="KEY"):
            one = kg.search_guides(number="P-92", get=lambda u, p: (200, json.dumps(
                {"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 1, "items": {"item": P92[1]}}}})))
            none = kg.search_guides(number="ZZ", get=lambda u, p: (200, _body([], code="03")))
        self.assertEqual((one.status, len(one.items)), ("OK", 1))
        self.assertEqual(none.status, "NO_DATA")

    def test_portal_xml_errors_never_leak_the_key(self):
        xml = ("<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
               "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode>"
               "</cmmMsgHeader></OpenAPI_ServiceResponse>")
        with patch("engine.kosha_guide._credential", return_value="SECRETKEY"):
            result = kg.search_guides(number="P-92", get=lambda u, p: (401, xml))
        self.assertEqual(result.status, "ERROR")
        self.assertNotIn("SECRETKEY", result.message)

    def test_network_failure_reports_error_without_the_key(self):
        def boom(url, params):
            raise kg.requests.ConnectionError(f"failed {params['serviceKey']}")

        with patch("engine.kosha_guide._credential", return_value="SECRETKEY"):
            result = kg.search_guides(number="P-92", get=boom)
        self.assertEqual(result.status, "ERROR")
        self.assertNotIn("SECRETKEY", result.message)


class BasisGuideTests(unittest.TestCase):
    def test_basis_list_names_the_guides_the_calculation_relies_on(self):
        numbers = {g["number"]: g for g in basis.basis_guides()}
        self.assertIn("P-92", numbers)
        self.assertEqual(numbers["P-92"]["cited_year"], 2012)

    def test_newer_edition_than_the_one_cited_is_flagged(self):
        with patch("engine.kosha_guide._credential", return_value="KEY"):
            statuses = basis.basis_status(get=lambda u, p: (200, _body(P92)))
        p92 = next(s for s in statuses if s.number == "P-92")
        self.assertTrue(p92.newer_than_cited)
        self.assertIn("P-92-2023", p92.summary)
        self.assertIn("새 판", p92.summary)

    def test_without_a_key_the_summary_says_lookup_was_skipped(self):
        with patch("engine.kosha_guide._credential", return_value=""):
            statuses = basis.basis_status()
        self.assertTrue(all(s.latest is None and s.lookup_status == "NOT_CONFIGURED" for s in statuses))
        self.assertIn("조회 안 됨", statuses[0].summary)


if __name__ == "__main__":
    unittest.main()
