from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from engine.stage2 import cap_ngii_lookup as ngii
from engine.stage2 import cap_site_lookup as lookup
from engine.stage2 import cap_form8_workspace as form8


class NGIIPoiTests(unittest.TestCase):
    def test_keyword_poi_uses_provider_geocode_and_filters_800_m(self):
        calls = []

        def fetch(params):
            calls.append(dict(params))
            if params["target"] == "geo":
                return {"search": {"header": {"target": "geo", "responseCode": 0},
                                   "contents": {"geo": {"x": "960000", "y": "1920000"}}}}
            return {"search": {"header": {"target": "poi", "responseCode": 0, "totalCount": 4},
                               "contents": {"poi": [
                                   {"name": "학교", "x": "960300", "y": "1920400", "typeName": "교육 > 학교", "roadAdres": "울산 남구"},
                                   {"name": "먼 학교", "x": "961000", "y": "1920000"},
                                   {"name": "", "x": "960001", "y": "1920000"},
                                   {"name": "좌표 오류", "x": "NaN", "y": "1920000"},
                               ]}}}

        with patch.dict(os.environ, {ngii.ENV_KEY: "private-key", ngii.REFERRER_KEY: "http://localhost:8501"}):
            found, notes = ngii.search("울산 남구 사평로 119", ["학교"], get=fetch)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].distance_m, 500)
        self.assertEqual(found[0].category, "")
        self.assertIn("학교", found[0].name)
        self.assertIn("학교", found[0].address)
        self.assertEqual(form8.candidate_row(found[0])["보호대상 구분"], "갑종")
        self.assertEqual(calls[0]["target"], "geo")
        self.assertEqual(calls[1]["target"], "poi")
        self.assertEqual(calls[1]["refrnUrl"], "http://localhost:8501")
        self.assertNotIn("private-key", " ".join(notes))

    def test_missing_referrer_and_unbounded_keywords_do_not_claim_coverage(self):
        with patch.dict(os.environ, {ngii.ENV_KEY: "key", ngii.REFERRER_KEY: ""}):
            found, notes = ngii.search("울산", ["학교"], get=lambda params: self.fail("network"))
        self.assertFalse(found)
        self.assertIn(ngii.REFERRER_KEY, " ".join(notes))
        with patch.dict(os.environ, {ngii.ENV_KEY: "key", ngii.REFERRER_KEY: "http://localhost:8501"}):
            found, notes = ngii.search("울산", [], get=lambda params: self.fail("network"))
        self.assertFalse(found)
        self.assertIn("반경 검색을 제공하지 않습니다", " ".join(notes))

    def test_ngii_only_works_without_kakao_and_keeps_other_sources_separate(self):
        candidate = lookup.Candidate("한빛초등학교", "", "", "울산 남구", 280, "국토정보플랫폼 검색 API")
        with patch.dict(os.environ, {lookup.ENV_KEY: "", "VWORLD_API_KEY": "", ngii.ENV_KEY: "key",
                                   ngii.REFERRER_KEY: "http://localhost:8501"}):
            found, message = lookup.find_combined_candidates("울산 남구 사평로 119", ngii_keyword="한빛초등학교",
                ngii_search=lambda address, terms: ([candidate], ["POI 1건"]),
                environment_search=lambda lat, lon: self.fail("No WGS84 point"))
        self.assertEqual(found, [candidate])
        self.assertIn("POI 1건", message)
        self.assertIn("주소 좌표가 없어", message)


if __name__ == "__main__":
    unittest.main()
