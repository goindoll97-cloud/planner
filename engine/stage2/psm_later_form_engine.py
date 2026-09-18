from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from . import psm_baseline_docx as baseline
from . import statutory_report as report
from .project import Stage2Project


CONDITIONAL_FORMS = ("17-2", "17-3", "17-4", "17-5", "18", "19", "20")
REQUIRED_FORMS = ("21",)


@dataclass(frozen=True)
class PSMLaterFormReadiness:
    form_no: str
    form_name: str
    applicability: str
    rows: tuple[tuple[str, ...], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.blockers


def _missing(value: object) -> bool:
    return value in (None, "", report.MISSING)


def _norm(value: object) -> str:
    return report._norm(value)


def _applicability_rows(project: Stage2Project) -> dict[str, Mapping[str, object]]:
    rows = report._rows(project, "psm.psi.form_applicability")
    out: dict[str, Mapping[str, object]] = {}
    for row in rows:
        form_no = str(report._row_value(row, "서식번호", "form_no") or "").strip()
        if form_no and form_no != report.MISSING:
            out[form_no] = row
    return out


def _parse_applicability(row: Mapping[str, object] | None) -> tuple[str, str]:
    if row is None:
        return "", ""
    raw = report._row_value(row, "적용여부", "적용 여부", "applicability")
    basis = report._row_value(row, "확인근거", "근거", "basis")
    raw = "" if raw == report.MISSING else str(raw).strip()
    basis = "" if basis == report.MISSING else str(basis).strip()
    normalized = _norm(raw)
    if normalized in {"해당없음", "미적용", "아니오", "없음"}:
        return "해당 없음", basis
    if normalized in {"적용", "예", "해당"}:
        return "적용", basis
    return raw, basis


def _row_missing_headers(
    headers: Sequence[str],
    row: Sequence[str],
    required_indexes: Sequence[int],
) -> list[str]:
    missing: list[str] = []
    for index in required_indexes:
        value = row[index] if index < len(row) else ""
        if _missing(value):
            missing.append(headers[index])
    return missing


def _validate_rows(form_no: str, rows: tuple[tuple[str, ...], ...]) -> list[str]:
    spec = report.PSM_FORMS[form_no]
    headers = spec.headers
    blockers: list[str] = []

    if not rows:
        return [f"{spec.reference} {spec.title}을 작성할 구조화 회사자료가 없습니다."]

    for row_index, row in enumerate(rows, start=1):
        missing: list[str] = []

        if form_no == "17-2":
            missing.extend(_row_missing_headers(headers, row, (0, 1, 6, 7, 8, 9)))
            setpoints = [row[i] if i < len(row) else "" for i in (2, 3, 4, 5)]
            if not any(not _missing(value) for value in setpoints):
                missing.append("설정값(온도·압력·액위·기타 중 최소 1개)")
        elif form_no == "17-3":
            missing.extend(_row_missing_headers(headers, row, (0,)))
            systems = [row[i] if i < len(row) else "" for i in range(1, len(headers))]
            if not any(not _missing(value) for value in systems):
                missing.append("소화설비 종류별 설치현황 중 최소 1개")
        elif form_no == "17-4":
            missing.extend(_row_missing_headers(headers, row, (0,)))
            systems = [row[i] if i < len(row) else "" for i in range(1, len(headers))]
            if not any(not _missing(value) for value in systems):
                missing.append("화재탐지·경보설비 종류별 설치현황 중 최소 1개")
        elif form_no == "17-5":
            missing.extend(_row_missing_headers(headers, row, tuple(range(0, len(headers) - 1))))
        elif form_no == "18":
            missing.extend(_row_missing_headers(headers, row, (0, 1, 2)))
        elif form_no == "19":
            missing.extend(_row_missing_headers(headers, row, tuple(range(len(headers)))))
        elif form_no == "20":
            missing.extend(_row_missing_headers(headers, row, (0, 1)))
            zones = [row[i] if i < len(row) else "" for i in (2, 3, 4)]
            if not any(not _missing(value) for value in zones):
                missing.append("0·1·2종 장소 선정기준 중 최소 1개")
        elif form_no == "21":
            missing.extend(_row_missing_headers(headers, row, tuple(range(len(headers)))))

        if missing:
            blockers.append(
                f"{spec.reference} {row_index}행에서 "
                + ", ".join(missing)
                + " 값이 확인되지 않았습니다."
            )

    return blockers


def build_psm_later_form_readiness(
    project: Stage2Project,
    form_no: str,
) -> PSMLaterFormReadiness:
    form_no = str(form_no)
    if form_no not in baseline.LATER_FORM_FIELDS:
        raise ValueError(f"지원하지 않는 PSM 후속 별지서식입니다: {form_no}")

    spec = report.PSM_FORMS[form_no]
    app_rows = _applicability_rows(project)
    applicability = "적용"
    basis = ""
    blockers: list[str] = []

    if form_no in CONDITIONAL_FORMS:
        applicability, basis = _parse_applicability(app_rows.get(form_no))
        if not applicability:
            blockers.append(
                f"{spec.reference} {spec.title}의 적용 여부가 확인되지 않았습니다. "
                "통합 작성자료의 PSM 조건부 서식 적용여부 표에서 '적용' 또는 '해당 없음'을 확인해 주세요."
            )
        elif applicability not in {"적용", "해당 없음"}:
            blockers.append(
                f"{spec.reference} {spec.title}의 적용여부 값 '{applicability}'을 해석할 수 없습니다. "
                "'적용' 또는 '해당 없음'으로 확인해 주세요."
            )
        if applicability in {"적용", "해당 없음"} and not basis:
            blockers.append(
                f"{spec.reference} {spec.title}의 적용여부 확인근거가 없습니다."
            )

        if applicability == "해당 없음" and not blockers:
            return PSMLaterFormReadiness(
                form_no=form_no,
                form_name=spec.title,
                applicability=applicability,
                rows=(),
                blockers=(),
                messages=(
                    f"{spec.reference} {spec.title}은 회사가 '해당 없음'으로 확인했습니다. 확인근거: {basis}",
                ),
            )

    field_keys = baseline.LATER_FORM_FIELDS[form_no]
    raw_rows = baseline._structured_rows(project, form_no, field_keys)
    rows = tuple(tuple(str(value or "") for value in row) for row in raw_rows)

    if not blockers:
        blockers.extend(_validate_rows(form_no, rows))

    messages: tuple[str, ...] = ()
    if not blockers:
        if form_no in CONDITIONAL_FORMS:
            messages = (
                f"{spec.reference} {spec.title}의 적용여부와 핵심 작성칸을 확인했습니다. 확인근거: {basis}",
            )
        else:
            messages = (
                f"{spec.reference} {spec.title}의 핵심 작성칸을 확인했습니다.",
            )

    return PSMLaterFormReadiness(
        form_no=form_no,
        form_name=spec.title,
        applicability=applicability,
        rows=rows,
        blockers=tuple(blockers),
        messages=messages,
    )


def build_all_psm_later_form_readiness(
    project: Stage2Project,
) -> tuple[PSMLaterFormReadiness, ...]:
    return tuple(
        build_psm_later_form_readiness(project, form_no)
        for form_no in (*CONDITIONAL_FORMS, *REQUIRED_FORMS)
    )
