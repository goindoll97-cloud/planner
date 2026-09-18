from __future__ import annotations

import re
from typing import Mapping

from .project import Stage2Project


PSM_CONDITIONAL_FORM_BY_REQUIREMENT = {
    "psm.psi.fire_protection": "17-3",
    "psm.psi.fire_detection": "17-4",
    "psm.psi.gas_detection": "17-5",
    "psm.psi.fireproofing": "18",
    "psm.psi.local_exhaust": "19",
    "psm.psi.ex_equipment": "20",
    "psm.risk.consequence": "19-2",
}


def _norm(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def requirement_explicitly_not_applicable(
    project: Stage2Project,
    requirement_key: str,
) -> bool:
    form_no = PSM_CONDITIONAL_FORM_BY_REQUIREMENT.get(str(requirement_key))
    if not form_no:
        return False

    record = project.get_field("psm.psi.form_applicability")
    if record is None or not isinstance(record.value, list):
        return False

    for row in record.value:
        if not isinstance(row, Mapping):
            continue
        normalized = {_norm(key): value for key, value in row.items()}
        row_form = str(
            normalized.get(_norm("서식번호"))
            or normalized.get(_norm("form_no"))
            or ""
        ).strip()
        if row_form != form_no:
            continue

        applicability = _norm(
            normalized.get(_norm("적용여부"))
            or normalized.get(_norm("applicability"))
            or ""
        )
        basis = str(
            normalized.get(_norm("확인근거"))
            or normalized.get(_norm("basis"))
            or ""
        ).strip()

        return (
            applicability in {"해당없음", "미적용", "아니오", "없음"}
            and bool(basis)
        )

    return False
