"""Stage-③ protection-target candidate edits, prepared for immediate draft output.

The operator selects category/subtype once. The choices are saved as PROPOSED
working facts, not final legal verification, and flow straight into Annex 8's
draft before any post-draft review. Missing or invalid facts remain explicit.
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
    saved_rows = form8.saved_rows(project)
    stored = {_key(row): row for row in saved_rows}
    reviewed = []
    visible_keys = set()
    for candidate in candidate_rows:
        row = dict(candidate)
        key = _key(candidate)
        visible_keys.add(key)
        old = stored.get(key)
        if old is not None:
            for column in EDITABLE_COLUMNS:
                # Explicitly cleared choices must NOT revert to name-only
                # suggestions when the page reruns.
                row[column] = _clean(old.get(column, ""))
        reviewed.append(row)
    # The document renderer uses ALL saved Annex-8 rows. Previously the UI
    # showed only *current* GIS candidates, so old/manual targets with empty
    # subtypes were invisible in Stage ③ yet appeared in the DOCX as
    # "[확인 필요: 세부유형]". Include them for the same edit/save workflow.
    for row in saved_rows:
        if _key(row) not in visible_keys:
            reviewed.append(dict(row))
            visible_keys.add(_key(row))
    return reviewed


def apply_candidate_edits(project, edited_rows: list[Mapping[str, Any]],
                          candidates: list[dict] | None = None) -> tuple[bool, list[str]]:
    """Save draft choices once, without a legal approval or review prerequisite.

    The geometry, GIS distance and addresses come only from the map survey.
    Existing targets absent from the current candidate list are preserved.
    A category/subtype mismatch clears the invalid subtype for later correction.
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
    # Clicking the save button for the first time must stage ALL candidates,
    # even when every proposed classification is unchanged. Otherwise 20
    # searched facilities silently disappear from the draft until somebody
    # edits at least one dropdown.
    source_columns = ("주소·위치", "좌표", "사업장 경계와 거리(m)",
                      "검색 출처·검색일", "GIS/현장 근거")
    has_new_or_updated_gis = any(
        (_key(row) not in previous_by_key)
        or any(_clean(row.get(col)) != _clean(previous_by_key[_key(row)].get(col))
               for col in source_columns)
        for row in updated
    )
    if not changed and not has_new_or_updated_gis:
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
    form8.save(project, merged, no_target=False, scope_reviewed=False, status="PROPOSED")
    form8.invalidate_review(project)
    return True, warnings
