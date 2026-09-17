from __future__ import annotations

from typing import Any

from .guidance import (
    ACTION_EXCEL,
    ACTION_FILE,
    ACTION_PROGRAM,
    ACTION_REVIEW,
    STATIC_WORKBOOK_LOCATIONS,
    RequirementGuidance,
)
from .intake import IntakeRequirement
from .project import Stage2Project


PREF_KEY = "stage2_workflow"
ATTACHMENT_MODE_MANUAL = "MANUAL_SEPARATE"
ATTACHMENT_MODE_PROGRAM = "PROGRAM_MANAGED"
ATTACHMENT_MODES = {ATTACHMENT_MODE_MANUAL, ATTACHMENT_MODE_PROGRAM}
DRAFT_WITH_HOLDS_KEY = "draft_with_holds_acknowledged"

BUCKET_CORE_INPUT = "CORE_INPUT"
BUCKET_AI_TEXT = "AI_TEXT"
BUCKET_MANUAL_ATTACHMENT = "MANUAL_ATTACHMENT"
BUCKET_FILE = "FILE"
BUCKET_REVIEW = "REVIEW"
BUCKET_PROGRAM = "PROGRAM"

_ATTACHMENT_KIND_TOKENS = (
    "DRAWING",
    "DOCUMENT",
    "ANALYSIS",
    "ATTACHMENT",
)


def _prefs(project: Stage2Project) -> dict[str, Any]:
    raw = project.stage1_snapshot.get(PREF_KEY)
    if not isinstance(raw, dict):
        raw = {}
        project.stage1_snapshot[PREF_KEY] = raw
    return raw


def attachment_mode(project: Stage2Project) -> str:
    value = str(_prefs(project).get("attachment_mode") or ATTACHMENT_MODE_MANUAL)
    return value if value in ATTACHMENT_MODES else ATTACHMENT_MODE_MANUAL


def set_attachment_mode(project: Stage2Project, mode: str) -> None:
    if mode not in ATTACHMENT_MODES:
        raise ValueError(f"지원하지 않는 첨부자료 처리방식입니다: {mode}")
    prefs = _prefs(project)
    if prefs.get("attachment_mode") == mode:
        return
    prefs["attachment_mode"] = mode
    prefs["intake_confirmed"] = False
    prefs["validation_confirmed"] = False
    prefs[DRAFT_WITH_HOLDS_KEY] = False
    project.touch()


def intake_confirmed(project: Stage2Project) -> bool:
    return bool(_prefs(project).get("intake_confirmed", False))


def validation_confirmed(project: Stage2Project) -> bool:
    return bool(_prefs(project).get("validation_confirmed", False))


def draft_with_holds_acknowledged(project: Stage2Project) -> bool:
    return bool(_prefs(project).get(DRAFT_WITH_HOLDS_KEY, False))


def draft_authoring_allowed(project: Stage2Project) -> bool:
    """Allow Stage 5 either after clean validation or explicit draft-only acknowledgement.

    This does not change final validation state.  The override exists only so a
    user can build review drafts while unresolved HOLD/REVIEW items remain
    visible and fail-closed for final submission readiness.
    """
    return validation_confirmed(project) or draft_with_holds_acknowledged(project)


def mark_intake_confirmed(project: Stage2Project, value: bool = True) -> None:
    prefs = _prefs(project)
    prefs["intake_confirmed"] = bool(value)
    if not value:
        prefs["validation_confirmed"] = False
        prefs[DRAFT_WITH_HOLDS_KEY] = False
    project.touch()


def mark_validation_confirmed(project: Stage2Project, value: bool = True) -> None:
    prefs = _prefs(project)
    prefs["validation_confirmed"] = bool(value)
    if value:
        prefs[DRAFT_WITH_HOLDS_KEY] = False
    project.touch()


def mark_draft_with_holds_acknowledged(project: Stage2Project, value: bool = True) -> None:
    prefs = _prefs(project)
    prefs[DRAFT_WITH_HOLDS_KEY] = bool(value)
    project.touch()


def reset_after_intake_change(project: Stage2Project) -> None:
    prefs = _prefs(project)
    prefs["intake_confirmed"] = False
    prefs["validation_confirmed"] = False
    prefs[DRAFT_WITH_HOLDS_KEY] = False
    project.touch()


def input_kind_has_attachment(input_kind: str) -> bool:
    kind = str(input_kind or "").upper()
    return any(token in kind for token in _ATTACHMENT_KIND_TOKENS)


def _fields_are_attachment_only(field_keys: tuple[str, ...]) -> bool:
    if not field_keys:
        return False
    return all(key.startswith("documents.") or key == "psm.psi.msds" for key in field_keys)


def item_depends_on_attachment(item: IntakeRequirement) -> bool:
    fields = tuple(item.missing_fields + item.received_unconfirmed_fields)
    return input_kind_has_attachment(item.input_kind) or _fields_are_attachment_only(fields)


def stage3_bucket(
    project: Stage2Project,
    item: IntakeRequirement,
    guidance: RequirementGuidance,
) -> str:
    """Classify what the Stage 3 user actually needs to do.

    In text-first mode, drawings/images/supporting documents are deliberately
    deferred to the responsible employee instead of blocking report-text
    authoring. Missing report-specific narrative fields are queued for the local
    AI drafting step; core workbook facts/tables remain mandatory inputs.
    """
    manual = attachment_mode(project) == ATTACHMENT_MODE_MANUAL
    attachment_dependent = item_depends_on_attachment(item)

    if attachment_dependent:
        return BUCKET_MANUAL_ATTACHMENT if manual else BUCKET_FILE

    if guidance.action_type == ACTION_PROGRAM:
        return BUCKET_PROGRAM
    if guidance.action_type == ACTION_REVIEW:
        return BUCKET_REVIEW
    if guidance.action_type == ACTION_FILE:
        return BUCKET_MANUAL_ATTACHMENT if manual else BUCKET_FILE

    if guidance.action_type == ACTION_EXCEL:
        missing = tuple(item.missing_fields)
        # Static workbook sheets contain source-of-truth company facts and
        # structured tables. Report-specific dynamic sheets are narrative
        # authoring fields that the local AI may draft from confirmed facts.
        if missing and all(key not in STATIC_WORKBOOK_LOCATIONS for key in missing):
            return BUCKET_AI_TEXT
        return BUCKET_CORE_INPUT

    return BUCKET_REVIEW
