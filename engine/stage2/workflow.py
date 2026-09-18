from __future__ import annotations

import hashlib
import json
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
VALIDATION_FINGERPRINT_KEY = "validation_fingerprint"

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


def _validation_fingerprint_payload(project: Stage2Project) -> dict[str, Any]:
    """Return the source-of-truth payload covered by Stage 4 validation.

    Runtime workflow flags and AI-authored draft prose are intentionally excluded:
    they do not change the company facts, legal scope, calculations, or evidence
    that Stage 4 validated. Any other field/scope/source change makes the stored
    validation fingerprint stale and forces a fresh Stage 4 confirmation.
    """
    fields: dict[str, Any] = {}
    for key in sorted(project.fields):
        if key.startswith("ai_draft."):
            continue
        record = project.fields[key]
        fields[key] = {
            "label": record.label,
            "value": record.value,
            "status": record.status,
            "note": record.note,
            "evidence": [
                {
                    "source_type": ev.source_type,
                    "source_name": ev.source_name,
                    "sha256": ev.sha256,
                    "page": ev.page,
                    "location": ev.location,
                    "note": ev.note,
                }
                for ev in record.evidence
            ],
        }

    stage1_snapshot = {
        key: value
        for key, value in project.stage1_snapshot.items()
        if key != PREF_KEY
    }
    return {
        "psm_required": project.psm_required,
        "cap_required": project.cap_required,
        "cap_group": project.cap_group,
        "scope_confirmed": project.scope_confirmed,
        "psm_selected": project.psm_selected,
        "cap_selected": project.cap_selected,
        "stage1_source_fingerprint": project.stage1_source_fingerprint,
        "stage1_snapshot": stage1_snapshot,
        "fields": fields,
    }


def validation_fingerprint(project: Stage2Project) -> str:
    payload = json.dumps(
        _validation_fingerprint_payload(project),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    prefs.pop(VALIDATION_FINGERPRINT_KEY, None)
    prefs[DRAFT_WITH_HOLDS_KEY] = False
    project.touch()


def intake_confirmed(project: Stage2Project) -> bool:
    return bool(_prefs(project).get("intake_confirmed", False))


def validation_confirmed(project: Stage2Project) -> bool:
    prefs = _prefs(project)
    if not bool(prefs.get("validation_confirmed", False)):
        return False
    stored = str(prefs.get(VALIDATION_FINGERPRINT_KEY) or "").strip()
    if not stored:
        # Legacy projects with only the old Boolean flag must be re-confirmed.
        return False
    return stored == validation_fingerprint(project)


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
        prefs.pop(VALIDATION_FINGERPRINT_KEY, None)
        prefs[DRAFT_WITH_HOLDS_KEY] = False
    project.touch()


def mark_validation_confirmed(project: Stage2Project, value: bool = True) -> None:
    prefs = _prefs(project)
    prefs["validation_confirmed"] = bool(value)
    if value:
        prefs[VALIDATION_FINGERPRINT_KEY] = validation_fingerprint(project)
        prefs[DRAFT_WITH_HOLDS_KEY] = False
    else:
        prefs.pop(VALIDATION_FINGERPRINT_KEY, None)
    project.touch()


def mark_draft_with_holds_acknowledged(project: Stage2Project, value: bool = True) -> None:
    prefs = _prefs(project)
    prefs[DRAFT_WITH_HOLDS_KEY] = bool(value)
    project.touch()


def reset_after_intake_change(project: Stage2Project) -> None:
    prefs = _prefs(project)
    prefs["intake_confirmed"] = False
    prefs["validation_confirmed"] = False
    prefs.pop(VALIDATION_FINGERPRINT_KEY, None)
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
