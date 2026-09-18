from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import statutory_report as report
from .project import Stage2Project


@dataclass(frozen=True)
class PSMCoreFormReadiness:
    form_no: str
    form_name: str
    rows: tuple[tuple[str, ...], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.blockers


_BUILDERS: dict[str, Callable[[Stage2Project], list[list[str]]]] = {
    "13": report._psm_form13_rows,
    "14": report._psm_form14_rows,
    "15": report._psm_form15_rows,
    "16": report._psm_form16_rows,
    "17": report._psm_form17_rows,
}

_OPTIONAL_HEADERS: dict[str, set[str]] = {
    "13": {"비고"},
    "14": {"비고"},
    "15": {"비고"},
    "16": {"비고"},
    "17": set(),
}


def _missing(value: object) -> bool:
    return value in (None, "", report.MISSING)


def build_psm_core_form_readiness(
    project: Stage2Project,
    form_no: str,
) -> PSMCoreFormReadiness:
    form_no = str(form_no)
    if form_no not in _BUILDERS:
        raise ValueError(f"지원하지 않는 PSM 핵심 별지서식입니다: {form_no}")

    spec = report.PSM_FORMS[form_no]
    raw_rows = _BUILDERS[form_no](project)
    rows = tuple(tuple(str(value or "") for value in row) for row in raw_rows)
    blockers: list[str] = []

    if not rows:
        blockers.append(
            f"{spec.reference} {spec.title}을 작성할 구조화 회사자료가 없습니다."
        )
    else:
        optional = _OPTIONAL_HEADERS[form_no]
        for row_index, row in enumerate(rows, start=1):
            missing_headers: list[str] = []
            for col_index, header in enumerate(spec.headers):
                if header in optional:
                    continue
                value = row[col_index] if col_index < len(row) else ""
                if _missing(value):
                    missing_headers.append(header)
            if missing_headers:
                blockers.append(
                    f"{spec.reference} {row_index}행에서 "
                    + ", ".join(missing_headers)
                    + " 값이 확인되지 않았습니다. 적용되지 않는 항목은 빈칸으로 두지 말고 "
                      "회사 확인값으로 '해당 없음'을 입력해 주세요."
                )

    return PSMCoreFormReadiness(
        form_no=form_no,
        form_name=spec.title,
        rows=rows,
        blockers=tuple(blockers),
        messages=(
            f"{spec.reference} {spec.title}의 핵심 작성칸을 확인했습니다.",
        ) if not blockers else (),
    )


def build_all_psm_core_form_readiness(
    project: Stage2Project,
) -> tuple[PSMCoreFormReadiness, ...]:
    return tuple(
        build_psm_core_form_readiness(project, form_no)
        for form_no in ("13", "14", "15", "16", "17")
    )
