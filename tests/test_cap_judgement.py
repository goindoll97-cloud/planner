from __future__ import annotations

from types import SimpleNamespace
import unittest

from engine.stage2 import cap_judgement as jd
from engine.stage2 import cap_start
from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests

BUSINESS = {"사업장명": "가상화학", "사업장 주소": "울산광역시 남구", "업종 또는 주요 생산품": "화학제품 제조"}
CAP1 = "화학사고예방관리계획서 작성·제출 대상 — 1군"
PSM_YES = "공정안전보고서 제출 대상"
PSM_NO = "현재 확인 범위에서 공정안전보고서 제출 대상 기준 미해당"
REQUEST_MAJOR = "'상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부'를 Y/N으로 확인하여 작성해 주세요."
REQUEST_EXEMPT = "'법 제23조제1항 단서 해당 여부'를 Y/N으로 확인하여 작성해 주세요."


def _decision(cap=CAP1, psm=PSM_NO, requests=(), system=()):
    return SimpleNamespace(cap_status=cap, cap_explanation="근거 설명", psm_status=psm, psm_explanation="",
                           company_requests=list(requests), system_blockers=list(system), psm_r_value=None,
                           psm_legal_basis=[], cap_legal_basis=[], psm_ratio_rows=[], cap_quantity_rows=[])


def _pending_project(quantity=None):
    rows = [{"제품명": "염소", "CAS No.": "7782-50-5", "함량(%)": 100.0, "최대 동시보유량(ton)": quantity}]
    outcome = cap_start.start(BUSINESS, rows, assess=lambda intake: _decision())
    return outcome.project if quantity is None else None


class BuildIntakeTests(unittest.TestCase):
    def test_pending_site_waits_until_a_quantity_is_known(self):
        project = _pending_project()
        self.assertTrue(jd.is_pending(project) and jd.undecided(project))
        result = jd.judge(project, assess=lambda intake: self.fail("양을 모르면 엔진을 부르면 안 된다"))
        self.assertEqual(result.status, "PENDING")
        self.assertEqual(result.missing_quantity, ("염소",))

    def test_quantities_come_from_the_facility_grid_when_the_company_left_them_blank(self):
        project = CAPForm1EngineTests()._project()  # 염소 설비를 이미 입력한 프로젝트(최대보유량 0.8 ton 계산)
        rows = project.get_field("inventory.chemicals").value
        for row in rows:
            row["최대 동시보유량(알면 입력)"] = None
        project.set_field("inventory.chemicals", "물질", rows, "USER_CONFIRMED")
        intake, missing = jd.build_intake(project)
        self.assertEqual(missing, [])
        self.assertEqual(float(intake.chemicals.iloc[0]["최대 동시보유량(알면 입력)"]), 0.8)

    def test_a_value_the_company_typed_wins_over_the_calculated_one(self):
        project = CAPForm1EngineTests()._project()
        rows = project.get_field("inventory.chemicals").value
        rows[0]["최대 동시보유량(알면 입력)"] = 3.0
        project.set_field("inventory.chemicals", "물질", rows, "USER_CONFIRMED")
        intake, _ = jd.build_intake(project)
        self.assertEqual(float(intake.chemicals.iloc[0]["최대 동시보유량(알면 입력)"]), 3.0)


class QuestionTests(unittest.TestCase):
    def _known(self):
        project = CAPForm1EngineTests()._project()
        project.stage1_snapshot["business"] = dict(BUSINESS)
        project.stage1_snapshot[jd.PENDING_KEY] = True
        project.scope_confirmed = False
        return project

    def test_only_the_questions_the_engine_asked_for_are_shown(self):
        project = self._known()
        result = jd.judge(project, assess=lambda intake: _decision(requests=[REQUEST_MAJOR]))
        self.assertEqual(result.status, "REQUEST")
        self.assertEqual([q.item for q in result.questions], ["상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부"])
        result = jd.judge(project, assess=lambda intake: _decision(requests=[REQUEST_MAJOR, REQUEST_EXEMPT]))
        self.assertEqual(len(result.questions), 2)

    def test_answers_are_saved_and_handed_to_the_engine_on_the_next_judgement(self):
        project = self._known()
        seen = {}

        def assess(intake):
            seen.update(intake.final_conditions)
            return _decision(requests=[] if seen else [REQUEST_MAJOR])
        jd.judge(project, assess=lambda intake: _decision(requests=[REQUEST_MAJOR]))
        jd.save_answers(project, {"상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부": "Y", "빈 칸": ""})
        self.assertNotIn("빈 칸", jd.answers(project))  # 비워 둔 답은 저장하지 않는다
        result = jd.judge(project, assess=assess)
        self.assertEqual(seen["상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부"], "Y")
        self.assertEqual(result.status, "DECIDED")

    def test_follow_up_question_appears_only_after_a_yes(self):
        project = self._known()
        first = jd.judge(project, assess=lambda intake: _decision(requests=[REQUEST_EXEMPT]))
        self.assertEqual([q.item for q in first.questions], ["법 제23조제1항 단서 해당 여부"])
        jd.save_answers(project, {"법 제23조제1항 단서 해당 여부": "Y"})
        again = jd.judge(project, assess=lambda intake: _decision(requests=[REQUEST_EXEMPT]))
        self.assertEqual([q.item for q in again.questions], ["법 제23조제1항 단서 해당 여부", "법적 예외 적용 유형"])

    def test_requests_without_a_matching_question_are_still_reported(self):
        project = self._known()
        result = jd.judge(project, assess=lambda intake: _decision(requests=["물질명·CAS 확인이 필요합니다."]))
        self.assertEqual((result.status, result.questions), ("REQUEST", ()))
        self.assertEqual(result.messages, ("물질명·CAS 확인이 필요합니다.",))


class ApplyTests(unittest.TestCase):
    def _project(self):
        project = CAPForm1EngineTests()._project()
        project.stage1_snapshot["business"] = dict(BUSINESS)
        project.stage1_snapshot[jd.PENDING_KEY] = True
        project.scope_confirmed = False
        project.cap_required = project.psm_required = None
        return project

    def test_a_target_result_sets_scope_and_clears_the_pending_mark(self):
        project = self._project()
        result = jd.judge(project, assess=lambda intake: _decision(psm=PSM_YES))
        self.assertEqual((result.status, result.cap_target, result.psm_target, result.cap_group), ("DECIDED", True, True, "1군"))
        jd.apply(project, result)
        self.assertTrue(project.cap_in_scope and project.psm_in_scope)
        self.assertEqual(project.cap_group, "1군")
        self.assertFalse(jd.undecided(project))
        self.assertEqual(project.stage1_snapshot["decision"]["cap_status"], CAP1)

    def test_writing_only_one_of_two_targets_keeps_the_other_marked_as_required(self):
        project = self._project()
        result = jd.judge(project, assess=lambda intake: _decision(psm=PSM_YES))
        jd.apply(project, result, write_psm=False, write_cap=True)
        self.assertTrue(project.cap_in_scope)
        self.assertFalse(project.psm_in_scope)
        self.assertIs(project.psm_required, True)  # 법적 대상 여부는 그대로 남는다
        with self.assertRaises(ValueError):
            jd.apply(project, result, write_psm=False, write_cap=False)

    def test_not_required_is_recorded_without_any_scope(self):
        project = self._project()
        result = jd.judge(project, assess=lambda intake: _decision(cap="화학사고예방관리계획서 작성·제출 의무 없음", psm=PSM_NO))
        self.assertEqual(result.status, "NOT_REQUIRED")
        jd.apply(project, result)
        self.assertFalse(project.cap_in_scope or project.psm_in_scope)
        self.assertFalse(jd.undecided(project))  # 판정 결과는 기록되어 다시 '판정 전'으로 보이지 않는다

    def test_rejudging_can_change_an_earlier_result(self):
        project = self._project()
        jd.apply(project, jd.judge(project, assess=lambda intake: _decision(cap=CAP1, psm=PSM_NO)))
        self.assertTrue(project.cap_in_scope and not project.psm_in_scope)
        jd.apply(project, jd.judge(project, assess=lambda intake: _decision(cap="화학사고예방관리계획서 작성·제출 대상 — 2군", psm=PSM_YES)))
        self.assertTrue(project.cap_in_scope and project.psm_in_scope)
        self.assertEqual(project.cap_group, "2군")

    def test_system_blockers_and_invalid_input_never_apply(self):
        project = self._project()
        blocked = jd.judge(project, assess=lambda intake: _decision(system=["규정 DB 필요"]))
        self.assertEqual(blocked.status, "SYSTEM")
        with self.assertRaises(ValueError):
            jd.apply(project, blocked)
        self.assertTrue(jd.undecided(project))


if __name__ == "__main__":
    unittest.main()


class ScreenTests(unittest.TestCase):
    def _page(self, project, decision):
        from pathlib import Path
        from unittest.mock import patch

        from streamlit.testing.v1 import AppTest

        root = Path(__file__).resolve().parents[1]
        rows = [{"project_id": project.project_id, "company_name": project.company_name}]
        patches = [patch("engine.stage2.storage.list_projects", return_value=rows),
                   patch("engine.stage2.storage.load_project", return_value=project),
                   patch("engine.stage2.storage.save_project"),
                   patch("ui.cap_start_panel._gate_hold", return_value=False),
                   patch("engine.stage2.cap_judgement.assess_stage1_from_workbook", side_effect=decision)]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        # judge()의 기본 인자는 정의 시점에 묶이므로, 화면이 부르는 함수를 직접 대체한다
        import engine.stage2.cap_judgement as module

        original = module.judge
        self.addCleanup(lambda: setattr(module, "judge", original))
        module.judge = lambda proj, assess=None: original(proj, assess=decision)
        at = AppTest.from_file(str(root / "ui/cap_workspace_page.py"), default_timeout=90)
        at.session_state["_stage2_active_project_id"] = project.project_id
        at.run()
        return at

    def _project(self):
        project = CAPForm1EngineTests()._project()
        project.stage1_snapshot["business"] = dict(BUSINESS)
        project.stage1_snapshot[jd.PENDING_KEY] = True
        project.scope_confirmed = False
        project.cap_required = project.psm_required = None
        return project

    def test_a_pending_site_opens_the_page_with_the_judgement_panel_and_forms_usable(self):
        project = self._project()
        at = self._page(project, lambda intake: _decision())
        self.assertFalse(at.exception)
        self.assertTrue(any("판정 전" in e.label for e in at.expander))
        self.assertTrue(any(b.key == f"judge_run_{project.project_id}" for b in at.button))

    def test_questions_appear_answer_and_the_scope_is_started_from_the_page(self):
        project = self._project()
        answered = {}

        def decision(intake):
            answered.update(intake.final_conditions)
            return _decision(requests=[] if answered else [REQUEST_MAJOR])
        at = self._page(project, decision)
        at.button(key=f"judge_run_{project.project_id}").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("주요취급시설" in m.value for m in at.markdown))
        item = "상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부"
        at.radio(key=f"judge_q_{project.project_id}_{item}").set_value("Y")
        at.button(key=f"judge_answer_{project.project_id}").click().run()
        self.assertEqual(jd.answers(project)[item], "Y")
        self.assertTrue(any(b.key == f"judge_apply_{project.project_id}" for b in at.button))
        at.button(key=f"judge_apply_{project.project_id}").click().run()
        self.assertTrue(project.cap_in_scope)
        self.assertFalse(jd.undecided(project))
