from types import SimpleNamespace
import unittest

from engine.stage1_workbook import _build_cap_required_explanation, _build_psm_submission_explanation


class DecisionExplanationContractTests(unittest.TestCase):
    def test_psm_required_explanation_connects_law_and_company_facts(self) -> None:
        line = SimpleNamespace(
            legal_item_no=1,
            legal_substance="인화성 가스",
            controlling_basis="제조·취급",
            manufacture_handling_kg=6000.0,
            storage_kg=0.0,
            manufacture_handling_threshold_kg=5000.0,
            storage_threshold_kg=200000.0,
            manufacture_handling_ratio=1.2,
            storage_ratio=0.0,
            controlling_ratio=1.2,
        )
        result = SimpleNamespace(
            industry_trigger=True,
            quantity_trigger=True,
            r_value=1.2,
            ratio_lines=[line],
            base=SimpleNamespace(
                industry_code="20202",
                industry_match="합성수지 및 기타 플라스틱물질 제조업",
            ),
        )
        text = _build_psm_submission_explanation(result)
        self.assertIn("「산업안전보건법」 제44조제1항", text)
        self.assertIn("「산업안전보건법 시행령」 제43조제1항제3호", text)
        self.assertIn("한국표준산업분류 코드는 20202", text)
        self.assertIn("별표 13 비고 제7호", text)
        self.assertIn("합산한 값(R)이 1.2000", text)
        self.assertIn("제43조제2항 각 호의 제외설비에 해당하지 않는", text)
        self.assertIn("공정안전보고서 제출 대상", text)

    def test_cap_group1_explanation_connects_quantity_and_major_facility(self) -> None:
        final = SimpleNamespace(status="REQUIRED_GROUP_1")
        rows = [
            {
                "legal_substance": "포스겐",
                "cas": "75-44-5",
                "calculated_max_holding_ton": 1.6,
                "lower_quantity_ton": 0.5,
                "upper_quantity_ton": 1.0,
                "quantity_band": "상위 규정수량 이상",
            }
        ]
        text = _build_cap_required_explanation(final, rows)
        self.assertIn("「화학물질관리법」 제23조제1항", text)
        self.assertIn("포스겐(CAS 75-44-5)", text)
        self.assertIn("상위 규정수량 1 ton 이상", text)
        self.assertIn("「화학물질관리법 시행규칙」 제19조제8항", text)
        self.assertIn("제2조제1항제12의1", text)
        self.assertIn("작성수준 1군 사업장", text)

    def test_cap_group2_explanation_names_lower_and_upper_quantities(self) -> None:
        final = SimpleNamespace(status="REQUIRED_GROUP_2")
        rows = [
            {
                "legal_substance": "가상물질",
                "cas": "111-11-1",
                "confirmed_max_holding_ton": 2.0,
                "lower_quantity_ton": 1.0,
                "upper_quantity_ton": 5.0,
                "status": "LOWER_CANDIDATE",
            }
        ]
        text = _build_cap_required_explanation(final, rows)
        self.assertIn("하위 규정수량 1 ton 이상", text)
        self.assertIn("상위 규정수량 5 ton 미만", text)
        self.assertIn("제2조제1항제12의2", text)
        self.assertIn("작성수준 2군 사업장", text)


if __name__ == "__main__":
    unittest.main()
