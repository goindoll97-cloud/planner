from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace  # noqa: F401  (화면 테스트 스크립트가 쓴다)
import unittest

from engine.stage1_workbook import _known_psm_exclusion, _match_cap_exemption
from engine.stage2 import cap_judgement as jd
from tests.test_cap_judgement import BUSINESS
from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests

ROOT = Path(__file__).resolve().parents[1]

# 판정 엔진이 실제로 만들 수 있는 Y/N·숫자 요청(engine/stage1_workbook.py). 모두 답할 칸이 있어야 한다.
ENGINE_REQUESTS = [
    "05_최종판정조건: '가스를 전문으로 저장·판매하는 시설 내 가스 여부'를 Y/N으로 확인해 주세요.",
    "05_최종판정조건: '법 제23조제1항 단서 해당 여부'를 Y/N으로 확인하여 작성해 주세요.",
    "05_최종판정조건: '상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부'를 Y/N으로 확인하여 작성해 주세요.",
    "05_최종판정조건: '시행령 제43조제2항 제외설비 해당 여부'를 Y/N으로 확인하여 작성해 주세요.",
    "05_최종판정조건: 근거: 「산업안전보건법」 제44조제1항 → 별표 13 「유해·위험물질 규정량」 제1호(인화성 가스). 귀사의 취급물질·공정이 이 항목에 해당하는지 확인하여 Y/N으로 작성해 주세요.",
    "05_최종판정조건: 근거: 「산업안전보건법」 제44조제1항 → 별표 13 「유해·위험물질 규정량」 제2호(인화성 액체). 귀사의 취급물질·공정이 이 항목에 해당하는지 확인하여 Y/N으로 작성해 주세요.",
    "05_최종판정조건: 근거: 별표 13 「유해·위험물질 규정량」 제23호 발연황산(삼산화황 중량 65% 이상 80% 미만). 제품 SDS, 시험성적서 또는 제조사 자료에서 해당 성분 함량을 확인하여 숫자(%)로 작성해 주세요.",
    "05_최종판정조건: 근거: 별표 13 「유해·위험물질 규정량」 제42호 니트로셀룰로오스(질소 함유량 12.6% 이상). 제품 SDS, 시험성적서 또는 제조사 자료에서 해당 성분 함량을 확인하여 숫자(%)로 작성해 주세요.",
    "05_최종판정조건: '미확인 결정조건 존재 여부'가 Y로 작성되어 있습니다. 미확인 사항을 확인한 뒤 N으로 갱신해 주세요.",
]
INFO_REQUEST = "02_화학물질목록: CAS 하나로 확정할 수 없는 염·화합물군이 있습니다."
TABLE_REQUEST = "06_공정안전보고서_비고8제외수량: 전문 가스 저장·판매시설에 해당하는 가스의 별표 13 호수와 제외 제조·취급량/저장량을 작성해 주세요."


ALL_REQUESTS = [*ENGINE_REQUESTS, INFO_REQUEST, TABLE_REQUEST]  # 화면 테스트 스크립트에는 한글을 직접 쓰지 않고 번호로 넘긴다


class EveryRequestHasAnAnswerBoxTests(unittest.TestCase):
    def test_each_engine_request_maps_to_a_question(self):
        for request in ENGINE_REQUESTS:
            self.assertTrue(jd._questions_for([request], {}), request)

    def test_the_gas_facility_question_now_has_an_answer_box_and_a_plain_explanation(self):
        (question,) = jd._questions_for([ENGINE_REQUESTS[0]], {})
        self.assertEqual(question.item, jd.NOTE8_ITEM)
        self.assertEqual(question.options, jd.YES_NO)
        self.assertIn("충전소", question.text)
        self.assertIn("왜 묻나요", question.help)
        self.assertIn("대부분 '아니오'", question.help)

    def test_an_unknown_yes_no_request_still_gets_an_answer_box(self):
        request = "05_최종판정조건: '새로 생긴 확인 항목 여부'를 Y/N으로 확인해 주세요."
        question = jd.generic_question(request)
        self.assertEqual(question.item, "새로 생긴 확인 항목 여부")
        self.assertEqual(question.options, jd.YES_NO)
        self.assertEqual(jd._questions_for([request], {})[0].item, "새로 생긴 확인 항목 여부")
        self.assertIsNone(jd.generic_question("CAS 하나로 확정할 수 없는 염·화합물군이 있습니다."))

    def test_the_exemption_follow_up_offers_the_legal_types_and_the_engine_accepts_each_one(self):
        questions = jd._questions_for([ENGINE_REQUESTS[1]], {"법 제23조제1항 단서 해당 여부": "Y"})
        types = next(q for q in questions if q.item == "법적 예외 적용 유형")
        self.assertGreaterEqual(len(types.choices), 15)
        for label in types.choices:
            self.assertTrue(_match_cap_exemption(label), label)  # 고른 값이 엔진에서 통과한다
        self.assertIn("법적 예외가 관련 취급시설 전체에 적용되는지", [q.item for q in questions])

    def test_the_plant_exclusion_types_are_chosen_from_the_list_and_accepted_by_the_engine(self):
        questions = jd._questions_for([ENGINE_REQUESTS[3]], {"시행령 제43조제2항 제외설비 해당 여부": "Y"})
        types = next(q for q in questions if q.item == "시행령 제43조제2항 제외설비 유형")
        self.assertTrue(types.choices)
        for label in types.choices:
            self.assertTrue(_known_psm_exclusion(label), label)

    def test_numeric_special_component_questions_exist(self):
        smoking = jd._questions_for([ENGINE_REQUESTS[6]], {})[0]
        nitro = jd._questions_for([ENGINE_REQUESTS[7]], {})[0]
        self.assertTrue(smoking.numeric and nitro.numeric)
        self.assertEqual(smoking.options, ())


class PlainLanguageTests(unittest.TestCase):
    def test_every_question_is_one_short_line_and_the_explanation_lives_in_the_help(self):
        for question in jd.QUESTIONS:
            self.assertLessEqual(len(question.text), 80, question.text)
            self.assertTrue(question.help.startswith("**무슨 뜻인가요?**"), question.item)
            self.assertIn("**모르면?**", question.help, question.item)

    def test_the_terms_that_were_not_understood_are_explained(self):
        by_item = {q.item: q for q in jd.QUESTIONS}
        exemption = by_item["법 제23조제1항 단서 해당 여부"]
        self.assertIn("면제", exemption.text)
        self.assertIn("연구실", exemption.help)
        self.assertIn("주유소", exemption.help)
        liquid = by_item["별표 13 제2호 인화성 액체 해당 여부"]
        for word in ("인화점", "톨루엔", "SDS 제9항"):
            self.assertIn(word, liquid.help)
        self.assertIn("LPG", by_item["별표 13 제1호 인화성 가스 해당 여부"].help)


class Note8Tests(unittest.TestCase):
    def test_excluded_gas_amounts_are_saved_and_passed_to_the_judgement(self):
        project = CAPForm1EngineTests()._project()
        project.stage1_snapshot["business"] = dict(BUSINESS)
        jd.save_note8_rows(project, [{"별표13 호수": "1", "제조·취급 제외량(kg)": "100", "저장 제외량(kg)": "2000"},
                                     {"별표13 호수": "", "제조·취급 제외량(kg)": "", "저장 제외량(kg)": ""}])
        self.assertEqual(jd.note8_rows(project), [{"별표13 호수": "1", "제조·취급 제외량(kg)": "100", "저장 제외량(kg)": "2000"}])
        intake, _ = jd.build_intake(project)
        self.assertEqual(list(intake.psm_note8_exclusions["별표13 호수"]), ["1"])


class AskScreenTests(unittest.TestCase):
    def _run(self, indexes):
        from streamlit.testing.v1 import AppTest

        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from types import SimpleNamespace\n"
            "from unittest.mock import patch\n"
            "import streamlit as st\n"
            "from engine.stage2 import cap_judgement as jd\n"
            "from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests\n"
            "from ui import judgement_panel as panel\n"
            "if 'project' not in st.session_state:\n"
            "    st.session_state['project'] = CAPForm1EngineTests()._project()\n"
            "project = st.session_state['project']\n"
            "from tests.test_judgement_questions_plain import ALL_REQUESTS\n"
            "messages = [ALL_REQUESTS[i] for i in %r]\n"
            "outcome = SimpleNamespace(status='REQUEST', messages=tuple(messages), questions=jd._questions_for(messages, jd.answers(project)))\n"
            "with patch('engine.stage2.storage.save_project'):\n"
            "    panel._ask(project, outcome)\n"
        ) % (str(ROOT), list(indexes))
        return AppTest.from_string(code, default_timeout=60).run()

    def test_the_gas_facility_request_shows_a_labelled_radio_with_help_and_no_orphan_text(self):
        at = self._run([0])
        self.assertFalse(at.exception)
        radios = [r for r in at.radio if "충전소" in r.label]
        self.assertEqual(len(radios), 1)
        self.assertTrue(radios[0].help and "왜 묻나요" in radios[0].help)
        self.assertFalse(any("Y/N으로 확인해 주세요" in m.value for m in at.markdown))  # 답할 칸 없는 예전 안내문이 없다
        self.assertFalse(any("Y/N으로 확인해 주세요" in i.value for i in at.info))

    def test_yes_answer_reveals_required_followups_before_confirmation(self):
        at = self._run([1])  # 화학사고예방관리계획서 면제 여부
        self.assertFalse(at.exception)
        parent = next(r for r in at.radio if "작성하지 않아도 되는 시설" in r.label)
        parent.set_value("Y").run()
        self.assertFalse(at.exception)
        self.assertTrue(any("어떤 면제 시설" in s.label for s in at.selectbox))
        self.assertTrue(any("취급하는 시설 전체" in r.label for r in at.radio))
        self.assertTrue(any(b.label == "판정정보 확인하기" for b in at.button))

    def test_flammable_liquid_uses_product_selection_instead_of_retyping_quantities(self):
        at = self._run([5])
        self.assertFalse(at.exception)
        parent = next(r for r in at.radio if "인화성 액체" in r.label)
        parent.set_value("Y").run()
        self.assertFalse(at.exception)
        self.assertTrue(any("인화성 액체에 해당하는 제품" in m.label for m in at.multiselect))
        self.assertFalse(any("인화성 액체의 하루 최대 제조" in t.label for t in at.text_input))
        self.assertFalse(any("인화성 액체의 최대 저장량" in t.label for t in at.text_input))

    def test_questions_are_grouped_under_the_document_they_affect(self):
        at = self._run([2, 5])
        headings = [m.value for m in at.markdown]
        self.assertIn("**화학사고예방관리계획서**", headings)
        self.assertIn("**공정안전보고서**", headings)

    def test_requests_without_an_answer_type_are_shown_once_as_an_info_box(self):
        at = self._run([2, len(ENGINE_REQUESTS)])
        shown = [m.value for m in at.markdown]
        self.assertIn("• CAS 하나로 확정할 수 없는 염·화합물군이 있습니다.", shown)
        heading = next(m for m in at.markdown if m.value == "**함께 확인할 내용**")
        self.assertIn("물질 목록이나 시설 정보", heading.help)       # 설명은 ? 안에 있다
        self.assertEqual(len(at.info), 0)

    def test_the_excluded_gas_table_appears_when_the_engine_asks_for_it(self):
        at = self._run([0, len(ENGINE_REQUESTS) + 1])
        self.assertFalse(at.exception)
        self.assertTrue(any("규정량 계산에서 뺄 가스의 양" in m.value for m in at.markdown))


class ProductQuantityPickerTests(unittest.TestCase):
    """multiselect가 실제로 고른 제품의 수량을 kg로 정확히 더하는지(위젯 존재만이 아니라)."""

    def _project_with_products(self):
        project = CAPForm1EngineTests()._project()
        project.set_field(
            "inventory.chemicals", "화학물질 목록",
            [
                {"물질명": "톨루엔", "제품명": "톨루엔", "CAS 번호": "108-88-3", "함량(%)": "99",
                 "최대 제조·사용량": "2", "최대 저장량": "5", "수량 단위": "ton"},
                {"물질명": "아세톤", "제품명": "아세톤", "CAS 번호": "67-64-1", "함량(%)": "99",
                 "최대 제조·사용량": "500", "최대 저장량": "1000", "수량 단위": "kg"},
            ],
            "USER_CONFIRMED",
        )
        return project

    def test_totals_are_summed_in_kg_only_for_the_selected_products(self):
        from ui import judgement_panel as panel

        project = self._project_with_products()
        totals = panel._product_quantity_kg(project, {"톨루엔"})
        self.assertEqual(totals, {"mfg": 2000.0, "storage": 5000.0})  # ton -> kg
        both = panel._product_quantity_kg(project, {"톨루엔", "아세톤"})
        self.assertEqual(both, {"mfg": 2500.0, "storage": 6000.0})
        self.assertEqual(panel._product_quantity_kg(project, set()), {"mfg": 0.0, "storage": 0.0})

    def test_label_is_read_from_the_parent_applicability_question(self):
        from types import SimpleNamespace

        from ui import judgement_panel as panel

        q = SimpleNamespace(follows="별표 13 제2호 인화성 액체 해당 여부")
        self.assertEqual(panel._psm_label_from_followup(q), "인화성 액체")


if __name__ == "__main__":
    unittest.main()

