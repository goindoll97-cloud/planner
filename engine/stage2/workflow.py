from __future__ import annotations

from typing import Any

from .project import Stage2Project


PREF_KEY = "stage2_workflow"
ATTACHMENT_MODE_MANUAL = "MANUAL_SEPARATE"
ATTACHMENT_MODE_PROGRAM = "PROGRAM_MANAGED"
ATTACHMENT_MODES = {ATTACHMENT_MODE_MANUAL, ATTACHMENT_MODE_PROGRAM}


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
    project.touch()


def intake_confirmed(project: Stage2Project) -> bool:
    return bool(_prefs(project).get("intake_confirmed", False))


def validation_confirmed(project: Stage2Project) -> bool:
    return bool(_prefs(project).get("validation_confirmed", False))


def mark_intake_confirmed(project: Stage2Project, value: bool = True) -> None:
    prefs = _prefs(project)
    prefs["intake_confirmed"] = bool(value)
    if not value:
        prefs["validation_confirmed"] = False
    project.touch()


def mark_validation_confirmed(project: Stage2Project, value: bool = True) -> None:
    prefs = _prefs(project)
    prefs["validation_confirmed"] = bool(value)
    project.touch()


def reset_after_intake_change(project: Stage2Project) -> None:
    prefs = _prefs(project)
    prefs["intake_confirmed"] = False
    prefs["validation_confirmed"] = False
    project.touch()
