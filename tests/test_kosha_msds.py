import os
import unittest
from unittest.mock import Mock, patch

from engine.cap_sds_app1 import SDSApp1Option
from engine.kosha_msds import (
    _credential,
    _request_xml,
    match_app1_options,
    parse_search_xml,
    parse_section2_xml,
)


class KOSHAMSDSParsingTests(unittest.TestCase):
    def test_search_xml_requires_exact_cas_and_extracts_chem_id(self):
        xml = """
        <response><header><resultCode>00</resultCode></header><body><items>
          <item><chemId>001008</chemId><casNo>624-83-9</casNo><chemNameKor>메틸 이소시아네이트</chemNameKor></item>
          <item><chemId>999999</chemId><casNo>75-44-5</casNo><chemNameKor>포스겐</chemNameKor></item>
        </items></body></response>
        """
        rows = parse_search_xml(xml, "624-83-9")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["chem_id"], "001008")

    def test_section2_parser_collects_detail_text(self):
        # chemdetail02 is already scoped to MSDS Section 2.  The adapter keeps
        # all detail text and the APP1 matcher later accepts only explicit
        # hazard-group + category statements.
        xml = """
        <response><header><resultCode>00</resultCode></header><body><items>
          <item><msdsItemNameKor>가. 유해성·위험성 분류</msdsItemNameKor><itemDetail>급성 독성(흡입) : 구분 1|인화성 액체 : 구분 2</itemDetail></item>
          <item><msdsItemNameKor>나. 예방조치문구</msdsItemNameKor><itemDetail>열로부터 멀리하시오</itemDetail></item>
        </items></body></response>
        """
        result = parse_section2_xml(xml)
        self.assertEqual(
            result,
            ["급성 독성(흡입) : 구분 1", "인화성 액체 : 구분 2", "열로부터 멀리하시오"],
        )

    def test_exact_normalized_group_and_category_match(self):
        options = [
            SDSApp1Option("급성독성 (흡입)||1", "급성 유해성", "급성독성 (흡입)", 1, 1.0, 20.0),
            SDSApp1Option("인화성 액체||2", "물리적 위험성", "인화성 액체", 2, 5.0, 200.0),
        ]
        matched, unmatched = match_app1_options(
            ["급성 독성(흡입) : 구분 1", "인화성 액체 : 구분 2", "열로부터 멀리하시오"],
            options,
        )
        self.assertEqual(set(matched), {"급성독성 (흡입)||1", "인화성 액체||2"})
        self.assertEqual(unmatched, [])

    def test_no_category_is_ignored_not_inferred(self):
        options = [
            SDSApp1Option("급성독성 (흡입)||1", "급성 유해성", "급성독성 (흡입)", 1, 1.0, 20.0),
        ]
        matched, unmatched = match_app1_options(["급성 독성(흡입)"], options)
        self.assertEqual(matched, [])
        self.assertEqual(unmatched, [])


class KOSHAMSDSCredentialTests(unittest.TestCase):
    def test_raw_decoding_key_is_used_as_is(self):
        with patch.dict(os.environ, {"KOSHA_MSDS_SERVICE_KEY": "abcDEF123raw"}, clear=False):
            self.assertEqual(_credential(), "abcDEF123raw")

    def test_percent_encoded_encoding_key_is_decoded_once(self):
        # data.go.kr's "Encoding" key form; pasting it as-is would otherwise
        # get double-encoded by requests and rejected by the gateway with a
        # bare HTTP 403 before it ever reaches the XML business-error path.
        with patch.dict(
            os.environ,
            {"KOSHA_MSDS_SERVICE_KEY": "abcDEF123%2Bxyz%3D%3D"},
            clear=False,
        ):
            self.assertEqual(_credential(), "abcDEF123+xyz==")


class KOSHAMSDSRequestErrorTests(unittest.TestCase):
    def test_xml_business_error_is_surfaced_even_on_403_status(self):
        # data.go.kr returns its own XML error body (e.g. an unregistered or
        # not-yet-approved service key) alongside a non-200 HTTP status. The
        # real reason must reach the caller instead of a bare "403 Forbidden"
        # that raise_for_status() would raise before the body is ever read.
        response = Mock()
        response.text = (
            "<OpenAPI_ServiceResponse><cmmMsgHeader>"
            "<errMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</errMsg>"
            "<returnAuthMsg>등록되지 않은 서비스키</returnAuthMsg>"
            "<returnReasonCode>30</returnReasonCode>"
            "</cmmMsgHeader></OpenAPI_ServiceResponse>"
        )
        response.raise_for_status.side_effect = AssertionError(
            "raise_for_status should not be reached when the XML body already explains the error"
        )
        with patch("engine.kosha_msds.requests.get", return_value=response):
            with self.assertRaises(RuntimeError) as ctx:
                _request_xml("https://example.test/x", {}, timeout=5, key="k")
        self.assertIn("30", str(ctx.exception))
        self.assertIn("등록되지 않은 서비스키", str(ctx.exception))

    def test_opaque_non_api_failure_still_raises_via_raise_for_status(self):
        response = Mock()
        response.text = "<html>not an api response</html>"
        response.raise_for_status.side_effect = RuntimeError("boom")
        with patch("engine.kosha_msds.requests.get", return_value=response):
            with self.assertRaises(RuntimeError):
                _request_xml("https://example.test/x", {}, timeout=5, key="k")
        response.raise_for_status.assert_called_once()


if __name__ == "__main__":
    unittest.main()
