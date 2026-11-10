"""Stage-③ protection-target candidate edits, without legal auto-confirmation.

Only the legally enumerated category and subtype values can be selected in the
new-employee UI. Names alone are suggestions, not final legal classifications.
The user's edits remain HOLD until the full 500 m scope and sources are checked.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from . import cap_form8_workspace as form8
from . import scenario_survey

EDITABLE_COLUMNS = ("보호대상 구분", "세부유형", "거주민수", "근로자수", "GIS/현장 근거")
LEGAL_CATEGORIES = ("", *form8.CATEGORIES)
LEGAL_SUBTYPES = ("", *dict.fromkeys(
    item for values in form8.SUBTYPES.values() for item in values
))


def _clean(value: object) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return value.strip() if isinstance(value, str) else value


def _key(row: Mapping[str, Any]) -> str:
    return form8._norm(row.get("보호대상 명칭"))


def candidate_review_rows(project, candidates: list[dict] | None = None) -> list[dict[str, Any]]:
    """Show saved choices over map suggestions without changing GIS facts."""
    candidate_rows = candidates if candidates is not None else scenario_survey.candidate_rows(project)
    stored = {_key(row): row for row in form8.saved_rows(project)}
    reviewed = []
    for candidate in candidate_rows:
        row = dict(candidate)
        old = stored.get(_key(candidate))
        if old is not None:
            for column in EDITABLE_COLUMNS:
                # Explicitly cleared choices must NOT revert to name-only
                # suggestions when the page reruns.
                row[column] = _clean(old.get(column, ""))
        reviewed.append(row)
    return reviewed


def apply_candidate_edits(project, edited_rows: list[Mapping[str, Any]],
                          candidates: list[dict] | None = None) -> tuple[bool, list[str]]:
    """Persist only changed editable facts, not an unverified final approval.

    The geometry, GIS distance and addresses come only from the map survey.
    Existing targets absent from the current candidate list are preserved.
    A category/subtype mismatch clears the invalid subtype and asks for review.
    """
    original = candidate_review_rows(project, candidates)
    if len(original) != len(edited_rows):
        raise ValueError("보호대상 후보 행 수가 변경되었습니다. 지도를 다시 조회해 주세요.")
    previous = form8.saved_rows(project)
    previous_by_key = {_key(row): row for row in previous}
    updated: list[dict[str, Any]] = []
    warnings: list[str] = []
    changed = False
    for original_row, edited in zip(original, edited_rows):
        if _key(original_row) != _key(edited):
            raise ValueError("보호대상 명칭을 직접 수정할 수 없습니다. 지도를 다시 조회해 주세요.")
        row = dict(original_row)
        category = str(_clean(edited.get("보호대상 구분", row.get("보호대상 구분", ""))))
        subtype = str(_clean(edited.get("세부유형", row.get("세부유형", ""))))
        if category not in LEGAL_CATEGORIES:
            raise ValueError(f"{row['보호대상 명칭']}: 지원하지 않는 법정 구분입니다.")
        if subtype not in LEGAL_SUBTYPES:
            raise ValueError(f"{row['보호대상 명칭']}: 법정 세부유형 선택지에서 골라 주세요.")
        if subtype and subtype not in form8.SUBTYPES.get(category, ()):
            subtype = ""
            warnings.append(f"{row['보호대상 명칭']}: 선택한 구분에 해당하는 세부유형을 다시 골라 주세요.")
        row["보호대상 구분"], row["세부유형"] = category, subtype
        for col in EDITABLE_COLUMNS[2:]:
            value = _clean(edited.get(col, row.get(col, "")))
            if col in ("거주민수", "근로자수") and value != "":
                try:
                    numeric = float(value)
                    if not math.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
                        raise ValueError
                    value = int(numeric)
                except (ValueError, TypeError):
                    raise ValueError(f"{row['보호대상 명칭']}: {col}는 0 이상의 정수만 입력해 주세요.") from None
            row[col] = value
        for col in EDITABLE_COLUMNS:
            if _clean(row.get(col)) != _clean(original_row.get(col)):
                changed = True
                break
        updated.append(row)
    if not changed:
        return False, warnings

    # Do not erase independently entered targets outside the current map
    # candidate list; replace only matching names with edited candidate rows.
    changed_by_key = {_key(row): row for row in updated}
    merged = []
    for old in previous:
        key = _key(old)
        if key in changed_by_key:
            merged.append({**old, **changed_by_key.pop(key)})
        else:
            merged.append(old)
    merged.extend(changed_by_key.values())
    form8.save(project, merged, no_target=False, scope_reviewed=False, status="HOLD")
    form8.invalidate_review(project)
    return True, warnings
