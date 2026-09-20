from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

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
    "15": set(),
    "16": {"비고"},
    "17": set(),
}

_EXPLICIT_NOT_APPLICABLE = {"해당없음", "자료없음", "미설정", "대상아님"}


def _missing(value: object) -> bool:
    return value in (None, "", report.MISSING)


def _norm(value: object) -> str:
    return report._norm(value)


def _explicit_na(value: object) -> bool:
    return _norm(value) in _EXPLICIT_NOT_APPLICABLE


def _raw_rows(project: Stage2Project, *keys: str) -> list[Mapping[str, object]]:
    return report._rows(project, *keys)


def _validate_form13_semantics(row_index: int, row: tuple[str, ...]) -> list[str]:
    blockers: list[str] = []
    exposure = row[5] if len(row) > 5 else ""
    toxicity = row[6] if len(row) > 6 else ""
    vapor_pressure = row[9] if len(row) > 9 else ""
    abnormal = row[11] if len(row) > 11 else ""

    if exposure and not _explicit_na(exposure):
        normalized = _norm(exposure)
        if "twa" not in normalized and "시간가중평균" not in normalized:
            blockers.append(
                f"별지 제13호서식 {row_index}행 노출기준은 시간가중평균노출기준(TWA)을 식별할 수 있게 적어야 합니다."
            )

    if toxicity and not _explicit_na(toxicity):
        normalized = _norm(toxicity)
        missing_routes = [
            label for marker, label in (("경구", "경구"), ("경피", "경피"), ("흡입", "흡입"))
            if marker not in normalized
        ]
        if missing_routes:
            blockers.append(
                f"별지 제13호서식 {row_index}행 독성치는 경구·경피·흡입 독성정보를 각각 구분해 적어야 합니다. "
                f"현재 확인되지 않은 경로: {', '.join(missing_routes)}."
            )

    if vapor_pressure and not _explicit_na(vapor_pressure):
        if _norm(vapor_pressure) in {"기체", "액체", "고체", "gas", "liquid", "solid"}:
            blockers.append(
                f"별지 제13호서식 {row_index}행 증기압에는 물질상태가 아니라 압력값과 기준온도를 입력해 주세요."
            )

    if abnormal and not _explicit_na(abnormal):
        normalized = _norm(abnormal)
        if normalized in {"예", "유", "있음", "yes"}:
            blockers.append(
                f"별지 제13호서식 {row_index}행 이상반응은 단순 유무가 아니라 반응 상대물질과 조건을 확인해 주세요."
            )
    return blockers


def _validate_form14_semantics(
    project: Stage2Project,
    row_index: int,
    rendered_row: tuple[str, ...],
) -> list[str]:
    blockers: list[str] = []
    raw = _raw_rows(project, "psm.psi.machinery_list")
    source = raw[row_index - 1] if row_index - 1 < len(raw) else {}
    name = " ".join(
        str(report._row_value(source, key) or "")
        for key in ("기계명", "동력기계명", "형식", "기계종류")
    )
    normalized_name = _norm(name)
    spec_text = rendered_row[2] if len(rendered_row) > 2 else ""
    normalized_spec = _norm(spec_text)

    def require(markers: tuple[tuple[str, str], ...]) -> None:
        missing = [label for marker, label in markers if _norm(marker) not in normalized_spec]
        if missing:
            blockers.append(
                f"별지 제14호서식 {row_index}행 명세에서 {', '.join(missing)}을(를) 확인할 수 없습니다."
            )

    if any(token in normalized_name for token in ("펌프", "압축기", "pump", "compressor")):
        require((("처리량", "시간당 처리량"), ("토출압력", "토출측 압력"), ("회전수", "분당 회전수")))
    elif any(token in normalized_name for token in ("교반", "agitator", "mixer")):
        require((("임펠러반경", "임펠러 반경"), ("회전수", "분당 회전수")))
    elif any(token in normalized_name for token in ("양중", "호이스트", "크레인", "hoist", "crane")):
        require((("양중하중", "양중 가능 무게"), ("양중높이", "양중 높이")))
    return blockers


def _validate_form15_semantics(row_index: int, row: tuple[str, ...]) -> list[str]:
    blockers: list[str] = []
    note = row[17] if len(row) > 17 else ""
    normalized = _norm(note)
    if note and not any(
        marker in normalized
        for marker in ("법", "안전검사", "안전인증", "검사대상", "인증대상", "해당없음", "대상아님")
    ):
        blockers.append(
            f"별지 제15호서식 {row_index}행 비고에는 안전인증·안전검사 등 적용 법령/검사 여부를 확인해 적어 주세요. "
            "관련 대상이 아니면 '해당 없음'으로 확인해 주세요."
        )
    return blockers


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

            if form_no == "13":
                blockers.extend(_validate_form13_semantics(row_index, row))
            elif form_no == "14":
                blockers.extend(_validate_form14_semantics(project, row_index, row))
            elif form_no == "15":
                blockers.extend(_validate_form15_semantics(row_index, row))

    return PSMCoreFormReadiness(
        form_no=form_no,
        form_name=spec.title,
        rows=rows,
        blockers=tuple(blockers),
        messages=(
            f"{spec.reference} {spec.title}의 필수 작성칸과 규정상 의미요건을 확인했습니다.",
        ) if not blockers else (),
    )


def build_all_psm_core_form_readiness(
    project: Stage2Project,
) -> tuple[PSMCoreFormReadiness, ...]:
    return tuple(
        build_psm_core_form_readiness(project, form_no)
        for form_no in ("13", "14", "15", "16", "17")
    )
