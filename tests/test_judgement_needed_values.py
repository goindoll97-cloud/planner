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
ROW1_REQUEST = "02_화학물질목록: 1행 (염소 / 7782-50-5)의 법정 사업장 최대보유량을 확인하여 '최대 동시보유량'과 '최대보유량 법정 산정 여부=Y'를 작성해 주세요."


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
        self.assertIn("시설 입력", text)  # 다른 화면으로 가라는 말이 아니라 이 화면 안의 시설 입력을 안내한다
        self.assertNotIn("별지 제1호", text)


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
        helps = " ".join(str(m.help or "") for m in at.markdown)          # 설명은 ? 안에 들어 있다
        self.assertNotIn("사업장 최대보유량이란?", helps)  # 최대보유량은 다음 단계로 분리한다
        self.assertTrue(any("판정정보를 먼저 확인하면 다음 단계에서 최대보유량" in c.value for c in at.caption))
        self.assertNotIn("별지 제1호", " ".join(i.value for i in at.info) + helps.replace("별지 제1호와 같은 표", ""))
        self.assertFalse(any("02 시트" in m.value for m in at.markdown))
        self.assertEqual(len(at.info), 0)                                   # 긴 안내 상자는 없다

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


class InlineFacilityTests(unittest.TestCase):
    def _run(self, indexes):
        from streamlit.testing.v1 import AppTest

        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from types import SimpleNamespace\n"
            "from unittest.mock import patch\n"
            "import streamlit as st\n"
            "from engine.stage2 import cap_judgement as jd\n"
            "from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests\n"
            "from tests.test_judgement_needed_values import REAL_REQUESTS, ROW1_REQUEST\n"
            "from ui import judgement_panel as panel\n"
            "if 'project' not in st.session_state:\n"
            "    st.session_state['project'] = CAPForm1EngineTests()._project()\n"
            "project = st.session_state['project']\n"
            "ALL = REAL_REQUESTS + [ROW1_REQUEST]\n"
            "outcome = SimpleNamespace(status='REQUEST', messages=tuple(ALL[i] for i in %r), questions=())\n"
            "with patch('engine.stage2.storage.save_project'), patch('engine.stage2.cap_judgement.holding_target_names', return_value=['염소']):\n"
            "    panel._ask(project, outcome)\n"
        ) % (str(ROOT), list(indexes))
        return AppTest.from_string(code, default_timeout=60).run()

    def test_the_facility_table_is_offered_inside_the_judgement_when_the_holding_needs_facilities(self):
        at = self._run([4])  # 04_시설별최대보유량 요청만 있을 때
        self.assertFalse(at.exception)
        markdown = [m.value for m in at.markdown]
        self.assertIn("**시설 입력 — 사업장 최대보유량 계산**", markdown)
        self.assertGreaterEqual(len(list(at.get("arrow_data_frame"))), 1)  # 시설 표가 화면 안에 있다
        self.assertEqual(len(at.info), 0)                                    # 안내 상자 없이 표만 보인다
        self.assertFalse(any(b.label == "판정정보 확인하기" for b in at.button))
        self.assertTrue(any(b.label == "다음 단계로 이동" for b in at.button))
        self.assertNotIn("별지 제1호", " ".join(i.value for i in at.info))

    def test_the_facility_section_uses_engine_selected_substances_not_message_parsing(self):
        from pathlib import Path as _P

        panel = (_P(__file__).resolve().parents[1] / "ui/judgement_panel.py").read_text(encoding="utf-8")
        self.assertIn("holding_names = judgement.holding_target_names(project)", panel)
        self.assertNotIn("holding_names = _names_needing_holding(project, table_messages)", panel)
        self.assertIn("물질명은 자동으로 채워지며 바꿀 수 없습니다", panel)

    def test_no_facility_section_when_nothing_asks_for_it(self):
        at = self._run([0])
        self.assertNotIn("**시설 입력 — 사업장 최대보유량 계산**", [m.value for m in at.markdown])

    def test_the_facility_table_is_one_shared_component(self):
        from pathlib import Path as _P

        page = (_P(__file__).resolve().parents[1] / "ui/cap_workspace_page.py").read_text(encoding="utf-8")
        panel = (_P(__file__).resolve().parents[1] / "ui/judgement_panel.py").read_text(encoding="utf-8")
        self.assertIn('cap_facility_editor.render(project, "cap_form01")', page)
        self.assertIn('cap_facility_editor.render(', panel)
        self.assertIn('project, "judge_fac", on_saved=saved, compact=True, focus_names=needs_names', panel)


class FacilityQuantityIsLegalTests(unittest.TestCase):
    def test_a_quantity_computed_from_facilities_is_passed_to_the_engine_as_legally_calculated(self):
        from unittest.mock import patch

        project = CAPForm1EngineTests()._project()
        chem_rows = jd.chem._rows(project)[1]
        cas = jd._clean(chem_rows[0].get("CAS No.") or chem_rows[0].get("CAS 번호"))
        with patch.object(jd, "_facility_quantities", return_value={cas: 0.8}):
            intake, _ = jd.build_intake(project)
        first = intake.chemicals.iloc[0]
        self.assertEqual(float(first["최대 동시보유량(알면 입력)"]), 0.8)
        self.assertEqual(first["최대보유량 법정 산정 여부"], "Y")

    def test_a_value_the_user_typed_keeps_the_answer_the_user_gave(self):
        from unittest.mock import patch

        project = CAPForm1EngineTests()._project()
        jd.save_chemical_inputs(project, [{"최대 동시보유량(알면 입력)": "3", "최대보유량 법정 산정 여부": "N"}])
        with patch.object(jd, "_facility_quantities", return_value={}):
            intake, _ = jd.build_intake(project)
        first = intake.chemicals.iloc[0]
        self.assertEqual(first["최대보유량 법정 산정 여부"], "N")  # 사용자가 아니오라고 답했으면 그대로 넘긴다


if __name__ == "__main__":
    unittest.main()
