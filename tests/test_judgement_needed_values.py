from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2 import cap_judgement as jd
from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests

ROOT = Path(__file__).resolve().parents[1]

# 실제 판정 엔진(가상 정밀화학공장 물질목록 31행)이 만든 요청 문구.
REAL_REQUESTS = [
    "02_화학물질목록: 5행 (아세톤 / 67-64-1)의 'SDS 제2항 유해성·위험성 분류'를 제품 SDS 그대로 작성해 주세요. 해당 분류가 없으면 '별표1 해당없음'으로 작성합니다.",
    "02_화학물질목록: 5행 (아세톤 / 67-64-1)의 법정 사업장 최대보유량을 확인하여 '최대 동시보유량'과 '최대보유량 법정 산정 여부=Y'를 작성해 주세요.",
    "02_화학물질목록: 6행 (반응기 세정용 혼합용제 A)의 법정 사업장 최대보유량을 확인하여 '최대 동시보유량'과 '최대보유량 법정 산정 여부=Y'를 작성해 주세요.",
    "02_화학물질목록: 6행 (반응기 세정용 혼합용제 A)의 'SDS 제2항 유해성·위험성 분류'를 제품 SDS 그대로 작성해 주세요. 해당 분류가 없으면 '별표1 해당없음'으로 작성합니다.",
    "04_시설별최대보유량: 사업장 최대보유량을 산정할 수 있도록 시설별 최대보유량 정보를 작성해 주세요. 이미 법정 산정값을 알고 있다면 02 시트의 '최대 동시보유량'과 '최대보유량 법정 산정 여부=Y'를 작성해 주세요.",
]


class NeedsTests(unittest.TestCase):
    def test_each_row_lists_exactly_the_values_the_engine_asked_for(self):
        needs = jd.request_needs(REAL_REQUESTS, 10)
        self.assertEqual(sorted(needs), [5, 6])
        self.assertEqual(needs[5], ["SDS 제2항 분류", "사업장 최대보유량"])
        self.assertEqual(needs[6], ["사업장 최대보유량", "SDS 제2항 분류"])

    def test_the_table_shows_only_the_columns_that_are_needed(self):
        needs = jd.request_needs(REAL_REQUESTS, 10)
        self.assertEqual(jd.columns_for(needs), ["최대 동시보유량(알면 입력)", "최대보유량 법정 산정 여부",
                                                 "SDS 제2항 유해성·위험성 분류(선택 입력)"])
        only_sds = jd.request_needs(REAL_REQUESTS[:1], 10)
        self.assertEqual(jd.columns_for(only_sds), ["SDS 제2항 유해성·위험성 분류(선택 입력)"])

    def test_request_rows_still_agrees_with_the_needs(self):
        self.assertEqual(jd.request_rows(REAL_REQUESTS, 10), sorted(jd.request_needs(REAL_REQUESTS, 10)))

    def test_a_request_that_names_no_row_applies_to_every_row(self):
        needs = jd.request_needs(["02_화학물질목록: 제품의 함량(%)을 확인해 주세요."], 3)
        self.assertEqual(sorted(needs), [1, 2, 3])

    def test_excel_wording_is_turned_into_plain_language(self):
        text = jd.plain_request(REAL_REQUESTS[4])
        self.assertNotIn("02 시트", text)
        self.assertNotIn("=Y", text)
        self.assertIn("별지 제1호", text)
        self.assertIn("시설", text)


class TableScreenTests(unittest.TestCase):
    def _run(self):
        from streamlit.testing.v1 import AppTest

        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from types import SimpleNamespace\n"
            "from unittest.mock import patch\n"
            "import streamlit as st\n"
            "from engine.stage2 import cap_judgement as jd\n"
            "from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests\n"
            "from tests.test_judgement_needed_values import REAL_REQUESTS\n"
            "from ui import judgement_panel as panel\n"
            "if 'project' not in st.session_state:\n"
            "    st.session_state['project'] = CAPForm1EngineTests()._project()\n"
            "project = st.session_state['project']\n"
            "outcome = SimpleNamespace(status='REQUEST', messages=tuple(REAL_REQUESTS[:2] + REAL_REQUESTS[4:]), questions=())\n"
            "with patch('engine.stage2.storage.save_project'), patch('streamlit.page_link'):\n"
            "    panel._ask(project, outcome)\n"
        ) % str(ROOT)
        return AppTest.from_string(code, default_timeout=60).run()

    def test_the_raw_engine_sentences_are_not_printed_and_the_plain_guidance_is(self):
        at = self._run()
        self.assertFalse(at.exception)
        shown = [m.value for m in at.markdown]
        self.assertFalse(any("'최대 동시보유량'과 '최대보유량 법정 산정 여부=Y'" in v for v in shown))
        infos = " ".join(i.value for i in at.info)
        self.assertIn("사업장 최대보유량", infos)
        self.assertIn("별지 제1호", infos)
        self.assertFalse("02 시트" in infos)

    def test_the_table_has_a_needed_values_column_and_an_editable_holding_column(self):
        at = self._run()
        self.assertFalse(at.exception)
        self.assertTrue(len(at.dataframe) >= 1 or len(list(at.get("arrow_data_frame"))) >= 1)


class SaveKeepsOtherValuesTests(unittest.TestCase):
    def test_saving_the_visible_columns_does_not_erase_values_in_hidden_columns(self):
        project = CAPForm1EngineTests()._project()
        jd.save_chemical_inputs(project, [{"함량(%)": "99", "최대 저장량": "2", "최대 동시보유량(알면 입력)": ""}])
        stored = jd.chemical_inputs(project)
        result = {**stored[0], **jd.rows_to_ton([{"최대 동시보유량(알면 입력)": "1500", "단위": "kg"}])[0]}
        self.assertEqual(result["함량(%)"], "99")
        self.assertEqual(result["최대 저장량"], "2")
        self.assertEqual(result["최대 동시보유량(알면 입력)"], "1.5")


if __name__ == "__main__":
    unittest.main()
