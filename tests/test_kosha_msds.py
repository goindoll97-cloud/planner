import unittest

from engine.cap_sds_app1 import SDSApp1Option
from engine.kosha_msds import match_app1_options, parse_search_xml, parse_section2_xml


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


if __name__ == "__main__":
    unittest.main()
