from __future__ import annotations

"""Pure state resolution for the three-step legal judgement workflow.

The engine outcome describes what remains unresolved. This module maps that
outcome and an explicit user navigation choice to exactly one screen. It does
not make or alter any legal decision.
"""

from dataclasses import dataclass

PSM = "공정안전보고서"
HOLDING_STAGE = "holding"


@dataclass(frozen=True)
class WorkflowState:
    screen: str
    step: int
    can_enter_holding: bool = False


def may_enter_holding(*, has_holding_targets: bool, has_unknown_answer: bool,
                      all_required_answers_present: bool = True, inputs_confirmed: bool = True) -> bool:
    """Gate the optional holding detour without allowing incomplete form data through."""
    return bool(
        has_holding_targets
        and has_unknown_answer
        and all_required_answers_present
        and inputs_confirmed
    )


def is_psm_quantity_question(question) -> bool:
    item = str(getattr(question, "item", "") or "")
    return (
        getattr(question, "system", "") == PSM
        and item.startswith("별표 13 제")
        and ("하루 최대 제조·취급량(kg)" in item or "최대 저장량(kg)" in item)
    )


def resolve(outcome, *, selected_stage: str = "", has_holding_targets: bool = False,
            has_facility_request: bool = False, has_condition_inputs: bool = False,
            has_other_requests: bool = False, has_unknown_answer: bool = False) -> WorkflowState:
    """Resolve one UI screen from the engine result and explicit user choice.

    Precedence is intentional: composition and invalid/system errors must be
    resolved first; PSM quantities belong to step 2; an explicit holding-stage
    choice can bypass unresolved judgement questions only when eligible target
    materials exist; final results always win over stale session choices.
    """
    if outcome is None:
        return WorkflowState("start", 1)

    status = str(getattr(outcome, "status", "") or "")
    questions = tuple(getattr(outcome, "questions", ()) or ())
    if status == "COMPOSITION":
        return WorkflowState("composition", 1)
    if status == "INVALID":
        return WorkflowState("invalid", 1)
    if status == "SYSTEM":
        return WorkflowState("system", 1)
    if status == "PENDING":
        return WorkflowState("holding" if has_holding_targets else "holding_unavailable", 2)
    if status in {"DECIDED", "NOT_REQUIRED"}:
        return WorkflowState("final", 3)
    if status != "REQUEST":
        return WorkflowState("unmapped", 1)

    if questions and all(is_psm_quantity_question(question) for question in questions):
        return WorkflowState("psm_quantity", 2)

    if selected_stage == HOLDING_STAGE:
        if has_holding_targets:
            return WorkflowState("holding", 2)
        return WorkflowState("holding_unavailable", 2)

    if not questions and has_facility_request and not has_condition_inputs and not has_other_requests:
        return WorkflowState("holding" if has_holding_targets else "holding_unavailable", 2)

    if questions or has_condition_inputs:
        return WorkflowState(
            "questions", 1,
            can_enter_holding=may_enter_holding(
                has_holding_targets=has_holding_targets,
                has_unknown_answer=has_unknown_answer,
            ),
        )
    return WorkflowState("unmapped", 1)
