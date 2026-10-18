from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from engine import law_old_new as lon

# 법제처 행정규칙 신구법 본문 조회 가이드의 응답 항목 구조를 따른 예시
ADMRUL_PAYLOAD = {
    "AdmRulOldAndNewService": {
        "구조문_기본정보": {"행정규칙명": "화학사고예방관리계획서 작성 등에 관한 규정", "시행일자": "20250807",
                       "발령번호": "2025-100"},
        "신조문_기본정보": {"행정규칙명": "화학사고예방관리계획서 작성 등에 관한 규정", "시행일자": "20261201",
                       "발령번호": "2026-200", "제개정구분명": "일부개정"},
        "구조문목록": {"조문": [
            "제3조(작성대상) ① 사업장은 <b>매 5년</b>마다 계획서를 작성한다.",
            "제5조(제출) 계획서는 30일 전까지 제출한다.",
            "",
        ]},
        "신조문목록": {"조문": [
            "제3조(작성대상) ① 사업장은 <b>매 4년</b>마다 계획서를 작성한다.",
            "제5조(제출) 계획서는 30일 전까지 제출한다.",
            "제5조의2(전자제출) 계획서는 전자문서로 제출할 수 있다.",
        ]},
        "신구법존재여부": "Y",
    }
}


class ParseTests(unittest.TestCase):
    def test_rows_pair_old_and_new_articles(self):
        result = lon.parse_old_new(ADMRUL_PAYLOAD)
        self.assertEqual(result["status"], "OK")
        rows = result["rows"]
        self.assertEqual([(r["조문"], r["변경"]) for r in rows],
                         [("제3조", "개정"), ("제5조", "같음"), ("제5조의2", "신설")])
        self.assertNotIn("<b>", rows[0]["개정 전"])  # 강조 태그 제거
        self.assertIn("매 4년", rows[0]["개정 후"])
        self.assertEqual(result["new_info"]["시행일자"], "20261201")

    def test_deleted_article(self):
        payload = {"구조문목록": {"조문": ["제7조(보고) 보고한다."]}, "신조문목록": {"조문": ["제7조 <삭제>"]}}
        self.assertEqual(lon.parse_old_new(payload)["rows"][0]["변경"], "삭제")
        dated = {"구조문목록": {"조문": ["제7조(보고) 보고한다."]},
                 "신조문목록": {"조문": ["제7조 &lt;삭제 2026. 12. 1.&gt;"]}}
        row = lon.parse_old_new(dated)["rows"][0]
        self.assertEqual((row["변경"], row["개정 후"]), ("삭제", "제7조 <삭제 2026. 12. 1.>"))

    def test_no_comparison_and_unparseable(self):
        self.assertEqual(lon.parse_old_new({"신구법존재여부": "N"})["status"], "NO_COMPARISON")
        self.assertEqual(lon.parse_old_new({"전혀": "다른 응답"})["status"], "PARSE_FAILED")

    def test_single_string_and_dict_items(self):
        payload = {"구조문목록": {"조문": "제1조(목적) 옛 문장"},
                   "신조문목록": {"조문": [{"content": "제1조(목적) 새 문장"}]}}
        rows = lon.parse_old_new(payload)["rows"]
        self.assertEqual((rows[0]["개정 전"], rows[0]["개정 후"]), ("제1조(목적) 옛 문장", "제1조(목적) 새 문장"))


class FetchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _response(self, payload):
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def test_admrul_uses_id_and_caches_result(self):
        source = {"target": "admrul", "serial": "2100000999"}
        with patch.object(lon, "get_api_credential", return_value=("key", "env")), \
             patch.object(lon.requests, "get", return_value=self._response(ADMRUL_PAYLOAD)) as get:
            first = lon.fetch_old_new("CAP_DRAFT", source, cache_dir=self.cache)
            second = lon.fetch_old_new("CAP_DRAFT", source, cache_dir=self.cache)
        self.assertEqual(first["status"], "OK")
        self.assertEqual(second["rows"], first["rows"])
        self.assertEqual(get.call_count, 1)  # 두 번째는 캐시
        params = get.call_args.kwargs["params"]
        self.assertEqual((params["target"], params["ID"]), ("admrulOldAndNew", "2100000999"))

    def test_law_uses_mst(self):
        source = {"target": "law", "serial": "280000"}
        with patch.object(lon, "get_api_credential", return_value=("key", "env")), \
             patch.object(lon.requests, "get", return_value=self._response(ADMRUL_PAYLOAD)) as get:
            lon.fetch_old_new("CAP_RULE", source, cache_dir=self.cache)
        params = get.call_args.kwargs["params"]
        self.assertEqual((params["target"], params["MST"]), ("oldAndNew", "280000"))

    def test_missing_key_or_lookup_info(self):
        with patch.object(lon, "get_api_credential", return_value=("", "미설정")):
            self.assertEqual(lon.fetch_old_new("CAP_RULE", {"target": "law", "serial": "1"},
                                               cache_dir=self.cache)["status"], "API_KEY_MISSING")
        self.assertEqual(lon.fetch_old_new("X", {}, cache_dir=self.cache)["status"], "UNSUPPORTED")

    def test_network_error_is_reported_without_the_key(self):
        with patch.object(lon, "get_api_credential", return_value=("secretkey", "env")), \
             patch.object(lon.requests, "get", side_effect=RuntimeError("boom secretkey")):
            result = lon.fetch_old_new("CAP_RULE", {"target": "law", "serial": "1"}, cache_dir=self.cache)
        self.assertEqual(result["status"], "API_ERROR")
        self.assertNotIn("secretkey", result["message"])


if __name__ == "__main__":
    unittest.main()
