from __future__ import annotations

from types import SimpleNamespace
import unittest

from ui import judgement_workflow as workflow


def question(item="business condition", system="공통"):
    return SimpleNamespace(item=item, system=system)


def outcome(status, *, questions=(), messages=(), missing_quantity=()):
    return SimpleNamespace(
        status=status,
        questions=tuple(questions),
        messages=tuple(messages),
        missing_quantity=tuple(missing_quantity),
    )


class JudgementWorkflowStateTests(unittest.TestCase):
    def test_holding_detour_requires_target_unknown_answers_and_confirmed_inputs(self):
        self.assertTrue(workflow.may_enter_holding(
            has_holding_targets=True,
            has_unknown_answer=True,
        ))
        for kwargs in (
            {"has_holding_targets": False, "has_unknown_answer": True},
            {"has_holding_targets": True, "has_unknown_answer": False},
            {"has_holding_targets": True, "has_unknown_answer": True, "all_required_answers_present": False},
            {"has_holding_targets": True, "has_unknown_answer": True, "inputs_confirmed": False},
        ):
            self.assertFalse(workflow.may_enter_holding(**kwargs))

    def test_empty_and_final_states_override_navigation_choice(self):
        self.assertEqual(workflow.resolve(None).screen, "start")
        for status in ("DECIDED", "NOT_REQUIRED"):
            state = workflow.resolve(outcome(status), selected_stage=workflow.HOLDING_STAGE, has_holding_targets=True)
            self.assertEqual((state.screen, state.step), ("final", 3))

    def test_composition_invalid_and_system_states_have_fixed_precedence(self):
        for status, expected in (("COMPOSITION", "composition"), ("INVALID", "invalid"), ("SYSTEM", "system")):
            state = workflow.resolve(outcome(status), selected_stage=workflow.HOLDING_STAGE, has_holding_targets=True)
            self.assertEqual(state.screen, expected)

    def test_only_psm_quantity_questions_belong_to_step_two(self):
        question_set = (
            question("별표 13 제2호 하루 최대 제조·취급량(kg)", "공정안전보고서"),
            question("별표 13 제2호 최대 저장량(kg)", "공정안전보고서"),
        )
        state = workflow.resolve(outcome("REQUEST", questions=question_set))
        self.assertEqual((state.screen, state.step), ("psm_quantity", 2))

    def test_mixed_questions_stay_on_step_one_until_user_explicitly_opens_holding(self):
        req = outcome("REQUEST", questions=(question(),), messages=("more info",))
        initial = workflow.resolve(req, has_holding_targets=True, has_unknown_answer=True)
        self.assertEqual((initial.screen, initial.step), ("questions", 1))
        self.assertTrue(initial.can_enter_holding)

        selected = workflow.resolve(req, selected_stage=workflow.HOLDING_STAGE, has_holding_targets=True)
        self.assertEqual((selected.screen, selected.step), ("holding", 2))

    def test_holding_choice_without_target_falls_back_to_clear_unavailable_state(self):
        req = outcome("REQUEST", questions=(question(),), messages=("more info",))
        state = workflow.resolve(req, selected_stage=workflow.HOLDING_STAGE, has_holding_targets=False)
        self.assertEqual((state.screen, state.step), ("holding_unavailable", 2))

    def test_pending_requires_holding_even_when_targets_are_missing(self):
        req = outcome("PENDING", missing_quantity=("Toluene",))
        available = workflow.resolve(req, has_holding_targets=True)
        unavailable = workflow.resolve(req, has_holding_targets=False)
        self.assertEqual((available.screen, available.step), ("holding", 2))
        self.assertEqual((unavailable.screen, unavailable.step), ("holding_unavailable", 2))

    def test_facility_request_and_other_condition_inputs_do_not_skip_questions(self):
        req = outcome("REQUEST", messages=("facility needed", "chemical table needed"))
        state = workflow.resolve(
            req,
            has_holding_targets=True,
            has_facility_request=True,
            has_condition_inputs=True,
        )
        self.assertEqual((state.screen, state.step), ("questions", 1))

    def test_facility_only_request_routes_to_holding(self):
        req = outcome("REQUEST", messages=("facility needed",))
        state = workflow.resolve(req, has_holding_targets=True, has_facility_request=True)
        self.assertEqual((state.screen, state.step), ("holding", 2))

    def test_unmapped_request_is_not_hidden_by_facility_request(self):
        req = outcome("REQUEST", messages=("facility needed", "unmapped requirement"))
        state = workflow.resolve(
            req,
            has_holding_targets=True,
            has_facility_request=True,
            has_other_requests=True,
        )
        self.assertEqual(state.screen, "unmapped")

    def test_unknown_answers_do_not_change_the_engine_screen_automatically(self):
        req = outcome("REQUEST", questions=(question(),), messages=("more info",))
        state = workflow.resolve(req, has_holding_targets=True, has_unknown_answer=True)
        self.assertEqual(state.screen, "questions")
        self.assertTrue(state.can_enter_holding)


if __name__ == "__main__":
    unittest.main()
