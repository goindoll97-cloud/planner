from __future__ import annotations

import os
import tempfile
import unittest

from streamlit.testing.v1 import AppTest

from engine.stage2 import cap_judgement as j
from engine.stage2 import cap_start
from engine.stage2.storage import load_project, save_project

REQUESTS = [
    "05_최종판정조건: 근거: 「산업안전보건법」 제44조제1항 → 「산업안전보건법 시행령」 제43조제1항 및 별표 13 「유해·위험물질 규정량」 제1호(인화성 가스). 귀사의 취급물질·공정이 이 항목에 해당하는지 확인하여 Y/N으로 작성해 주세요.",
    "05_최종판정조건: 근거: 「산업안전보건법」 제44조제1항 → 「산업안전보건법 시행령」 제43조제1항 및 별표 13 「유해·위험물질 규정량」 제2호(인화성 액체). 귀사의 취급물질·공정이 이 항목에 해당하는지 확인하여 Y/N으로 작성해 주세요.",
    "02_화학물질목록: 1, 2, 3, 10의 최대 제조·사용량과 최대 저장량을 확인하여 작성해 주세요.",
    "02_화학물질목록: 2행 (이소프로필알코올 / 67-63-0)의 'SDS 제2항 유해성·위험성 분류'를 제품 SDS 그대로 작성해 주세요.",
    "02_화학물질목록: 3행 (아세톤 / 67-64-1)의 법정 사업장 최대보유량을 확인하여 '최대 동시보유량'과 '최대보유량 법정 산정 여부=Y'를 작성해 주세요.",
]


def _project(count=3, quantity="0.5"):
    rows = [{"제품명": f"물질{i}", "CAS No.": f"67-6{i}-0", "함량(%)": "99", "최대 동시보유량(ton)": quantity}
            for i in range(1, count + 1)]
    intake = cap_start.build_intake(
        {"회사명": "t", "사업장명": "t", "사업장 주소": "울산", "업종 또는 주요 생산품": "화학"}, rows)
    project = cap_start._pending(intake, ()).project
    project.project_id = "jp"
    return project


class JudgementInputTests(unittest.TestCase):
    def test_annex13_requests_become_questions_with_quantity_follow_ups_only_on_yes(self):
        questions = {q.item for q in j._questions_for(REQUESTS, {})}
        self.assertIn("별표 13 제1호 인화성 가스 해당 여부", questions)
        self.assertIn("별표 13 제2호 인화성 액체 해당 여부", questions)
        self.assertNotIn("별표 13 제1호 최대 저장량(kg)", questions)
        after_yes = {q.item for q in j._questions_for(REQUESTS, {"별표 13 제1호 인화성 가스 해당 여부": "Y"})}
        self.assertIn("별표 13 제1호 최대 저장량(kg)", after_yes)
        self.assertIn("별표 13 제1호 하루 최대 제조·취급량(kg)", after_yes)
        self.assertNotIn("별표 13 제2호 최대 저장량(kg)", after_yes)

    def test_request_rows_reads_row_numbers_and_falls_back_to_all_rows(self):
        self.assertEqual(j.request_rows(REQUESTS, 12), [1, 2, 3, 10])
        generic = REQUESTS + ["02_화학물질목록: 농도·성상 등 규정수량 결정에 필요한 항목을 확인하여 작성해 주세요."]
        self.assertEqual(j.request_rows(generic, 4), [1, 2, 3, 4])

    def test_entered_values_reach_the_judgement_input_and_count_as_a_quantity(self):
        project = _project(quantity="")
        self.assertEqual(j.judge(project).status, "PENDING")
        j.save_chemical_inputs(project, [
            {"최대 제조·사용량": "2", "SDS 제2항 유해성·위험성 분류(선택 입력)": "별표1 해당없음"}, {}, {}])
        intake, missing = j.build_intake(project)
        self.assertEqual(intake.chemicals.loc[0, "SDS 제2항 유해성·위험성 분류(선택 입력)"], "별표1 해당없음")
        self.assertEqual(str(intake.chemicals.loc[0, "최대 제조·사용량"]), "2")
        self.assertEqual(len(missing), 2)  # 값을 준 물질만 수량이 확인된 것으로 본다

    def test_untouched_projects_keep_the_original_seven_columns(self):
        intake, _ = j.build_intake(_project())
        self.assertEqual(len(intake.chemicals.columns), 7)


def _app():
    import streamlit as st

    from engine.stage2.storage import load_project
    from ui import judgement_panel

    judgement_panel.render(load_project("jp"))


class JudgementPanelTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        save_project(_project())

    def _screen(self):
        at = AppTest.from_function(_app, default_timeout=60)
        project = load_project("jp")
        at.session_state["judge_out_jp"] = j.Outcome(
            "REQUEST", tuple(REQUESTS), j._questions_for(REQUESTS, {}), decision=None)
        return at.run()

    def test_requests_now_show_answer_inputs_instead_of_a_dead_end(self):
        at = self._screen()
        self.assertFalse(at.exception)
        radios = [r.key for r in at.radio]
        self.assertTrue(any("제1호 인화성 가스" in k for k in radios))
        self.assertTrue(any("제2호 인화성 액체" in k for k in radios))
        self.assertEqual(len(at.get("arrow_data_frame")), 1)  # 물질별 입력 표

    def test_answering_saves_and_reaches_the_engine(self):
        at = self._screen()
        key = next(r.key for r in at.radio if "제1호 인화성 가스" in r.key)
        at.radio(key=key).set_value("N").run()
        at.button(key="judge_answer_jp").click().run()
        self.assertFalse(at.exception)
        saved = j.answers(load_project("jp"))
        self.assertEqual(saved.get("별표 13 제1호 인화성 가스 해당 여부"), "N")


if __name__ == "__main__":
    unittest.main()


class TemplateColumnTests(unittest.TestCase):
    def test_blank_template_has_the_judgement_columns_and_maps_back_to_them(self):
        from io import BytesIO

        from engine.stage2 import cap_chemical_upload as up

        data = up.blank_template()
        parsed = up.parse(data, "물질목록_양식.xlsx")
        self.assertEqual(
            set(parsed.mapping),
            {"제품명", "CAS No.", "함량(%)", "최대 제조·사용량", "최대 저장량", "단위"},
        )
        self.assertEqual(parsed.mapping["최대 제조·사용량"], "최대 제조·사용량")
        self.assertEqual(parsed.mapping["최대 저장량"], "최대 저장량")
        self.assertEqual(parsed.mapping["단위"], "단위")

    def test_minimal_template_converts_kg_quantities_to_ton_for_engine(self):
        import pandas as pd
        from io import BytesIO

        from engine.stage2 import cap_chemical_upload as up

        frame = pd.DataFrame(
            [["톨루엔", "108-88-3", "99.5", "3000", "12500", "kg"]],
            columns=["제품명", "CAS No.", "함량(%)", "최대 제조·사용량", "최대 저장량", "단위"],
        )
        buffer = BytesIO()
        frame.to_excel(buffer, index=False)
        parsed = up.parse(buffer.getvalue(), "minimal.xlsx")
        row = up.normalize(parsed, parsed.mapping)[0]
        self.assertEqual(row["최대 제조·사용량"], "3")
        self.assertEqual(row["최대 저장량"], "12.5")
        self.assertEqual(row["단위"], "ton")
        checked = up.check_rows([row])
        intake = cap_start.build_intake(
            {"사업장명": "t", "사업장 주소": "울산", "업종 또는 주요 생산품": "화학"},
            checked.rows,
        )
        chem = intake.chemicals.iloc[0]
        self.assertEqual(chem["최대 제조·사용량"], 3.0)
        self.assertEqual(chem["최대 저장량"], 12.5)
        self.assertEqual(chem["수량 단위"], "ton")

    def test_a_filled_template_row_carries_every_column_through_to_the_engine_input(self):
        import pandas as pd

        from engine.stage2 import cap_chemical_upload as up

        headers = ["제품명", "CAS No.", "함량(%)", "최대 동시보유량(ton)", "성상(상온·상압)",
                   "최대 제조·사용량(kg)", "최대 저장량(ton)", "최대보유량 법정 산정 여부",
                   "SDS 제2항 유해성·위험성 분류(선택 입력)"]
        frame = pd.DataFrame([["아세톤", "67-64-1", "99", "3", "액체", "500", "2", "Y", "별표1 해당없음"]], columns=headers)
        from io import BytesIO
        buffer = BytesIO()
        frame.to_excel(buffer, index=False)
        parsed = up.parse(buffer.getvalue(), "x.xlsx")
        row = up.normalize(parsed, parsed.mapping)[0]
        self.assertEqual(row["최대 제조·사용량"], "0.5")  # kg를 ton으로 바꿈
        self.assertEqual(row["최대 저장량"], "2")
        checked = up.check_rows([row])
        self.assertTrue(checked.rows[0]["_ok"])
        intake = cap_start.build_intake({"사업장명": "t"}, checked.rows)
        chem = intake.chemicals.iloc[0]
        self.assertEqual(chem["상온·상압 액체 여부(해당 시)"], "Y")
        self.assertEqual(chem["최대 저장량"], "2")
        self.assertEqual(chem["SDS 제2항 유해성·위험성 분류(선택 입력)"], "별표1 해당없음")

    def test_a_stored_project_row_feeds_the_judgement_input_without_asking_again(self):
        rows = [{"제품명": "물질1", "CAS No.": "67-61-0", "함량(%)": "99", "최대 동시보유량(ton)": "",
                 "최대 제조·사용량": "1", "상온·상압 액체 여부(해당 시)": "Y"}]
        intake = cap_start.build_intake(
            {"사업장명": "t", "사업장 주소": "울산", "업종 또는 주요 생산품": "화학"}, rows)
        project = cap_start._pending(intake, ()).project
        built, missing = j.build_intake(project)
        self.assertEqual(missing, [])
        self.assertEqual(built.chemicals.loc[0, "상온·상압 액체 여부(해당 시)"], "Y")


    def test_template_unit_column_is_a_kg_ton_dropdown(self):
        from io import BytesIO

        from openpyxl import load_workbook

        from engine.stage2 import cap_chemical_upload as up

        sheet = load_workbook(BytesIO(up.blank_template()))["물질 목록"]
        lists = {tuple(v.sqref.ranges)[0].coord: v.formula1 for v in sheet.data_validations.dataValidation if v.type == "list"}
        self.assertEqual(lists["F2:F1000"], '"kg,ton"')

    def test_state_choice_decides_the_liquid_answer_and_unknown_words_are_flagged(self):
        import pandas as pd
        from io import BytesIO

        from engine.stage2 import cap_chemical_upload as up

        frame = pd.DataFrame([["가", "67-64-1", "액체"], ["나", "7782-50-5", "기체"], ["다", "7647-01-0", "고체"],
                              ["라", "64-17-5", "반고체"]], columns=["제품명", "CAS No.", "성상(상온·상압)"])
        buffer = BytesIO()
        frame.to_excel(buffer, index=False)
        parsed = up.parse(buffer.getvalue(), "x.xlsx")
        rows = up.normalize(parsed, parsed.mapping)
        self.assertEqual([r["상온·상압 액체 여부(해당 시)"] for r in rows], ["Y", "N", "N", ""])
        self.assertIn("성상 '반고체'", rows[3]["메모"])
