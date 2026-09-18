from __future__ import annotations

"""Deterministic preparation for CAP Annex Forms 12 and 13.

Spatial modelling remains outside this module. KORA/GIS supplies confirmed
scenario distances, accident-origin coordinates and the overall impact-range
result. This engine validates/cross-links those facts and prepares statutory
text/table values without inventing geometry, people or protected targets.
"""

from dataclasses import dataclass
from collections.abc import Mapping
import math
import re
from typing import Any

from .project import CONFIRMED_STATUSES, Stage2Project


YES = {"예", "yes", "y", "true", "1", "없음", "해당"}
NO = {"아니오", "아니요", "no", "n", "false", "0", "있음", "미해당"}


@dataclass(frozen=True)
class CAPForm12Data:
    rows: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(self.rows) and not self.blockers


@dataclass(frozen=True)
class CAPForm13Data:
    summary: dict[str, Any]
    protected_targets: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]
    no_protected_targets: bool = False

    @property
    def ready(self) -> bool:
        return bool(self.summary) and not self.blockers


def _clean(value: object) -> str:
    # Numeric zero is a meaningful confirmed value for population/protected
    # target counts. Do not collapse it through a truthiness fallback.
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", _clean(value)).lower()


def _row_value(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, "") and _clean(value):
            return value
    return ""


def _num(value: object) -> float | None:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        number = float(match.group())
    return number if math.isfinite(number) else None


def _int_nonnegative(value: object) -> int | None:
    number = _num(value)
    if number is None or number < 0 or abs(number - round(number)) > 1e-9:
        return None
    return int(round(number))


def _confirmed_rows(project: Stage2Project, *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        rec = project.get_field(key)
        if rec is None or rec.status not in CONFIRMED_STATUSES:
            continue
        if isinstance(rec.value, list):
            rows = [dict(row) for row in rec.value if isinstance(row, Mapping)]
            if rows:
                return rows
    return []


def _confirmed_document(project: Stage2Project, key: str) -> bool:
    rec = project.get_field(key)
    return bool(
        rec is not None
        and rec.status in CONFIRMED_STATUSES
        and rec.value not in (None, "", {}, [])
    )


def _known_names(project: Stage2Project, key: str, aliases: tuple[str, ...]) -> set[str]:
    rows = _confirmed_rows(project, key)
    out: set[str] = set()
    for row in rows:
        value = _row_value(row, *aliases)
        if _clean(value):
            out.add(_norm(value))
    return out


def _yes_no(value: object) -> bool | None:
    n = _norm(value)
    if n in {_norm(v) for v in YES}:
        return True
    if n in {_norm(v) for v in NO}:
        return False
    return None


def build_cap_form12_data(project: Stage2Project) -> CAPForm12Data:
    rows = _confirmed_rows(
        project,
        "cap.offsite.scenario_impact_table",
        "cap.offsite.impact_range_result",
    )
    if not rows:
        return CAPForm12Data(
            (),
            ("KORA/GIS에서 확정된 사고시나리오별 영향평가 자료가 없습니다.",),
            (),
        )

    known_chemicals = _known_names(
        project,
        "inventory.chemicals",
        ("물질명", "유해화학물질명", "제품명"),
    )
    known_facilities = _known_names(
        project,
        "inventory.facilities",
        ("설비번호", "구분기호", "장치번호"),
    )

    blockers: list[str] = []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, row in enumerate(rows, start=1):
        scenario = _clean(_row_value(row, "사고시나리오명", "사고시나리오", "시나리오명"))
        label = scenario or f"{index}행"
        if not scenario:
            blockers.append(f"{label}: 사고시나리오명이 비어 있습니다.")
            continue
        if scenario in seen:
            blockers.append(f"{scenario}: 사고시나리오 영향평가 행이 중복되어 있습니다.")
            continue
        seen.add(scenario)

        chemical = _clean(_row_value(row, "유해화학물질명", "물질명"))
        facility = _clean(_row_value(row, "대상 설비번호", "설비번호", "구분기호"))
        accident_type = _clean(_row_value(row, "사고유형", "사고 유형"))
        distance = _num(_row_value(row, "장외거리(m)", "장외거리", "사고시나리오 거리(장외)"))
        residents = _int_nonnegative(_row_value(row, "거주민수", "거주민 수"))
        workers = _int_nonnegative(_row_value(row, "근로자수", "근로자 수"))
        a_count = _int_nonnegative(_row_value(row, "갑종 보호대상 수", "갑종수"))
        b_count = _int_nonnegative(_row_value(row, "을종 보호대상 수", "을종수"))
        env_count = _int_nonnegative(_row_value(row, "환경수용체 수", "환경수용체수"))
        origin = _clean(_row_value(row, "사고원점 좌표", "사고원점의 좌표", "사고원점"))
        evidence = _clean(_row_value(row, "KORA/GIS 근거", "KORA 결과근거", "근거자료"))

        if not chemical:
            blockers.append(f"{label}: 유해화학물질명이 비어 있습니다.")
        elif known_chemicals and _norm(chemical) not in known_chemicals:
            blockers.append(f"{label}: 물질 '{chemical}'을 회사 화학물질 목록과 연결하지 못했습니다.")

        if not facility:
            blockers.append(f"{label}: 대상 설비번호가 비어 있습니다.")
        elif known_facilities and _norm(facility) not in known_facilities:
            blockers.append(f"{label}: 대상 설비 '{facility}'를 회사 설비목록과 연결하지 못했습니다.")

        if not accident_type:
            blockers.append(f"{label}: 사고유형이 비어 있습니다.")
        if distance is None or distance < 0:
            blockers.append(f"{label}: 장외거리(m)를 0 이상의 KORA 확정 숫자로 입력해 주세요.")
        for name, value in (
            ("거주민수", residents),
            ("근로자수", workers),
            ("갑종 보호대상 수", a_count),
            ("을종 보호대상 수", b_count),
            ("환경수용체 수", env_count),
        ):
            if value is None:
                blockers.append(f"{label}: {name}를 0 이상의 정수로 확인해 주세요.")
        if not origin:
            blockers.append(f"{label}: 사고원점 좌표가 비어 있습니다.")
        if not evidence:
            blockers.append(f"{label}: KORA/GIS 결과 근거 식별자가 비어 있습니다.")

        out.append({
            "연번": len(out) + 1,
            "사고시나리오명": scenario,
            "유해화학물질명": chemical,
            "대상 설비번호": facility,
            "사고유형": accident_type,
            "장외거리(m)": "" if distance is None else distance,
            "거주민수": "" if residents is None else residents,
            "근로자수": "" if workers is None else workers,
            "갑종 보호대상 수": "" if a_count is None else a_count,
            "을종 보호대상 수": "" if b_count is None else b_count,
            "환경수용체 수": "" if env_count is None else env_count,
            "사고원점 좌표": origin,
            "KORA/GIS 근거": evidence,
        })

    messages = (
        "장외거리·사고원점·주민수·보호대상 수는 KORA/GIS 확정값만 사용하며 프로그램이 공간값을 추정하지 않습니다.",
    )
    return CAPForm12Data(
        rows=tuple(out),
        blockers=tuple(dict.fromkeys(blockers)),
        messages=messages,
    )


def build_cap_form13_data(project: Stage2Project) -> CAPForm13Data:
    summaries = _confirmed_rows(project, "cap.offsite.overall_impact_summary")
    targets = _confirmed_rows(project, "cap.offsite.population_and_protected_targets")
    if not summaries:
        return CAPForm13Data(
            {},
            (),
            ("총괄영향범위 GIS/KORA 확정요약이 없습니다.",),
            (),
            False,
        )
    if len(summaries) != 1:
        return CAPForm13Data(
            {},
            (),
            ("총괄영향범위 요약은 사업장당 1행으로 확인해 주세요.",),
            (),
            False,
        )

    raw = summaries[0]
    method = _clean(_row_value(raw, "총괄영향범위 산출방법", "산출방법"))
    result_summary = _clean(_row_value(raw, "총괄영향범위 결과 요약", "결과요약"))
    evidence = _clean(_row_value(raw, "GIS/KORA 근거", "근거자료"))
    no_targets_raw = _row_value(raw, "보호대상 없음 여부", "총괄영향범위 내 보호대상 없음 여부")
    no_targets = _yes_no(no_targets_raw)
    residents = _int_nonnegative(_row_value(raw, "총괄영향범위 내 거주민수", "거주민수"))
    workers = _int_nonnegative(_row_value(raw, "총괄영향범위 내 근로자수", "근로자수"))

    blockers: list[str] = []
    if not method:
        blockers.append("총괄영향범위 산출방법이 비어 있습니다.")
    if not result_summary:
        blockers.append("총괄영향범위 결과 요약이 비어 있습니다.")
    if not evidence:
        blockers.append("총괄영향범위 GIS/KORA 근거 식별자가 비어 있습니다.")
    if no_targets is None:
        blockers.append("총괄영향범위 내 보호대상 없음 여부를 예/아니오로 확인해 주세요.")
    if residents is None:
        blockers.append("총괄영향범위 내 거주민수를 0 이상의 정수로 확인해 주세요.")
    if workers is None:
        blockers.append("총괄영향범위 내 근로자수를 0 이상의 정수로 확인해 주세요.")

    if not _confirmed_document(project, "documents.kora_impact_result"):
        blockers.append(
            "총괄영향범위 형상과 공간분석을 확인할 KORA/GIS 결과파일이 첨부·확인되지 않았습니다."
        )

    out_targets: list[dict[str, Any]] = []
    if no_targets is False and not targets:
        blockers.append("보호대상이 존재한다고 확인했지만 총괄영향범위 내 보호대상 명세가 없습니다.")
    if no_targets is True and targets:
        blockers.append("보호대상 없음으로 확인했지만 보호대상 명세 행이 함께 존재합니다.")

    allowed_classes = {"갑종", "을종", "환경수용체"}
    if no_targets is not True:
        seen: set[tuple[str, str]] = set()
        for index, row in enumerate(targets, start=1):
            name = _clean(_row_value(row, "보호대상 명칭", "명칭"))
            category = _clean(_row_value(row, "보호대상 구분", "구분", "보호대상 종류"))
            subtype = _clean(_row_value(row, "세부유형", "종류"))
            location = _clean(_row_value(row, "주소·위치", "주소", "위치"))
            coordinate = _clean(_row_value(row, "좌표", "보호대상 좌표"))
            distance = _num(_row_value(row, "사업장 경계와 거리(m)", "거리(m)", "거리"))
            people = _int_nonnegative(_row_value(row, "인원수", "주민수", "수용인원"))
            row_evidence = _clean(_row_value(row, "GIS 근거", "근거자료"))
            label = name or f"{index}행"

            if not name:
                blockers.append(f"{label}: 보호대상 명칭이 비어 있습니다.")
            if category not in allowed_classes:
                blockers.append(f"{label}: 보호대상 구분은 갑종/을종/환경수용체 중 하나로 입력해 주세요.")
            if not subtype:
                blockers.append(f"{label}: 보호대상 세부유형이 비어 있습니다.")
            if not location and not coordinate:
                blockers.append(f"{label}: 주소·위치 또는 좌표가 필요합니다.")
            if distance is None or distance < 0:
                blockers.append(f"{label}: 사업장 경계와 거리(m)를 0 이상의 GIS 확정값으로 입력해 주세요.")
            if people is None:
                blockers.append(f"{label}: 인원수는 0 이상의 정수로 확인해 주세요.")
            if not row_evidence:
                blockers.append(f"{label}: GIS 근거 식별자가 비어 있습니다.")

            identity = (_norm(name), category)
            if name and identity in seen:
                blockers.append(f"{label}: 동일 보호대상 명칭·구분이 중복되어 있습니다.")
            seen.add(identity)

            out_targets.append({
                "일련번호": len(out_targets) + 1,
                "보호대상 명칭": name,
                "보호대상 구분": category,
                "보호대상 종류": subtype,
                "주소·위치": location,
                "좌표": coordinate,
                "사업장 경계와 거리(m)": "" if distance is None else distance,
                "인원수": "" if people is None else people,
                "GIS 근거": row_evidence,
            })

    summary = {
        "총괄영향범위 산출방법": method,
        "총괄영향범위 결과 요약": result_summary,
        "GIS/KORA 근거": evidence,
        "총괄영향범위 내 거주민수": "" if residents is None else residents,
        "총괄영향범위 내 근로자수": "" if workers is None else workers,
        "보호대상 없음 여부": "예" if no_targets is True else ("아니오" if no_targets is False else ""),
    }
    messages = (
        "총괄영향범위 형상은 개별 장외거리의 최대값으로 대체하지 않고 확인된 GIS/KORA 결과를 사용합니다.",
        "보호대상 목록은 총괄영향범위와 공간적으로 중첩된 대상을 회사/GIS가 확정한 경우에만 작성합니다.",
    )
    return CAPForm13Data(
        summary=summary,
        protected_targets=tuple(out_targets),
        blockers=tuple(dict.fromkeys(blockers)),
        messages=messages,
        no_protected_targets=no_targets is True,
    )
