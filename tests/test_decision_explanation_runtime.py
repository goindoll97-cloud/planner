from __future__ import annotations

import unittest
from types import SimpleNamespace

from engine.psm_followup import PSMFollowupFacts, PSMPropertyAnswer, PSMRatioLine
from engine.stage1_workbook import _cap_subject_explanation, _psm_subject_explanation


class DecisionExplanationRuntimeTests(unittest.TestCase):
    def test_psm_quantity_explanation_contains_actual_company_basis(self) -> None:
        ratio = PSMRatioLine(
            legal_item_no=14,
            legal_substance='포스겐',
            manufacture_handling_kg=250.0,
            storage_kg=1600.0,
            manufacture_handling_threshold_kg=500.0,
            storage_threshold_kg=5000.0,
            manufacture_handling_ratio=0.5,
            storage_ratio=0.32,
            controlling_ratio=0.5,
            controlling_basis='제조·취급',
        )
        result = SimpleNamespace(
            industry_trigger=False,
            quantity_trigger=True,
            r_value=1.25,
            ratio_lines=[ratio],
            base=SimpleNamespace(industry_code='', industry_match=''),
        )
        text = _psm_subject_explanation(result, PSMFollowupFacts())
        self.assertIn('「산업안전보건법」 제44조제1항', text)
        self.assertIn('합산한 값(R)이 1.25로 1 이상', text)
        self.assertIn('포스겐', text)
        self.assertIn('C/T=0.5', text)
        self.assertIn('제43조제2항의 제외설비에는 해당하지 않는', text)

    def test_psm_industry_explanation_contains_20202_condition(self) -> None:
        facts = PSMFollowupFacts(property_answers={1: PSMPropertyAnswer(applicable=True, manufacture_handling_kg=100.0, storage_kg=0.0)})
        result = SimpleNamespace(
            industry_trigger=True,
            quantity_trigger=False,
            r_value=0.1,
            ratio_lines=[],
            base=SimpleNamespace(industry_code='20202', industry_match='합성수지 및 기타 플라스틱물질 제조업'),
        )
        text = _psm_subject_explanation(result, facts)
        self.assertIn('한국표준산업분류 코드 20202', text)
        self.assertIn('제43조제1항제3호', text)
        self.assertIn('별표 13 제1호 인화성 가스', text)

    def test_cap_group1_explanation_contains_holding_and_quantities(self) -> None:
        final_cap = SimpleNamespace(status='REQUIRED_GROUP_1')
        rows = [{
            'product_name': '포스겐',
            'cas': '75-44-5',
            'calculated_max_holding_ton': 1.6,
            'lower_quantity_ton': 0.5,
            'upper_quantity_ton': 1.0,
            'quantity_band': 'UPPER_OR_MORE',
        }]
        text = _cap_subject_explanation(final_cap, rows)
        self.assertIn('「화학물질관리법」 제23조제1항', text)
        self.assertIn('포스겐(CAS 75-44-5)', text)
        self.assertIn('최대보유량 1.6 ton', text)
        self.assertIn('상위 규정수량 1 ton', text)
        self.assertIn('주요취급시설', text)
        self.assertIn('작성수준 1군 사업장', text)


if __name__ == '__main__':
    unittest.main()
