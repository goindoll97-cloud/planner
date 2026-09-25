from __future__ import annotations

"""Fail-closed preparation for CAP Annex Form 8 site-surroundings data.

The program does not discover nearby receptors by itself. Form 8 is populated
only from company/GIS/field-confirmed structured rows. Distances and receptor
classification therefore remain auditable source facts rather than AI guesses.
"""

from dataclasses import dataclass
from collections.abc import Mapping
import math
import re
from typing import Any

from .project import CONFIRMED_STATUSES, Stage2Project


_ALLOWED_CLASSES = {"갑종", "을종", "환경수용체"}


@dataclass(frozen=True)
class CAPForm8Data:
    rows: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]
    no_protected_targets: bool = False

    @property
    def ready(self) -> bool:
        return (bool(self.rows) or self.no_protected_targets) and not self.blockers


def _clean(value: object) -> str:
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


def _yes_no(value: object) -> bool | None:
    token = _norm(value)
    if token in {_norm(v) for v in ("예", "yes", "y", "true", "1", "없음", "해당없음")}:
        return True
    if token in {_norm(v) for v in ("아니오", "아니요", "no", "n", "false", "0", "있음")}:
        return False
    return None


def _confirmed_rows(project: Stage2Project) -> list[dict[str, Any]]:
    rec = project.get_field("cap.site.surrounding_environment")
    if rec is None or rec.status not in CONFIRMED_STATUSES or not isinstance(rec.value, list):
        return []
    return [dict(row) for row in rec.value if isinstance(row, Mapping)]


def build_cap_form8_data(project: Stage2Project) -> CAPForm8Data:
    source_rows = _confirmed_rows(project)
    if not source_rows:
        return CAPForm8Data(
            (),
            ("사업장 주변 보호대상 정보를 구조화된 GIS/현장 확인표로 제출해 주세요.",),
            (),
            False,
        )

    blockers: list[str] = []
    messages: list[str] = []
    rows: list[dict[str, Any]] = []
    explicit_no_target = False
    seen: set[tuple[str, str]] = set()

    for index, raw in enumerate(source_rows, start=1):
        none_state = _yes_no(_row_value(raw, "보호대상 없음 여부", "500m 내 보호대상 없음 여부"))
        evidence = _clean(_row_value(raw, "GIS/현장 근거", "GIS 근거", "근거자료", "확인근거"))
        scope_checked = _yes_no(_row_value(raw, "500m 범위 전체 확인")) is True
        if not scope_checked:
            blockers.append(f"{index}행: 사업장 경계 바깥 500m 범위 전체를 지도/GIS/현장 자료로 검토했는지 확인해 주세요.")
        if none_state is True:
            explicit_no_target = True
            if not evidence:
                blockers.append(f"{index}행: 보호대상 없음 확인에는 GIS/현장 근거가 필요합니다.")
            continue

        name = _clean(_row_value(raw, "보호대상 명칭", "명칭"))
        category = _clean(_row_value(raw, "보호대상 구분", "구분"))
        subtype = _clean(_row_value(raw, "세부유형", "보호대상 종류", "종류"))
        address = _clean(_row_value(raw, "주소·위치", "주소", "위치"))
        coordinate = _clean(_row_value(raw, "좌표", "보호대상 좌표"))
        distance = _num(_row_value(raw, "사업장 경계와 거리(m)", "거리(m)", "거리"))
        search_distance = _num(_row_value(raw, "검색결과 거리(주소점 기준, 참고)"))

        label = name or f"{index}행"
        if not name:
            blockers.append(f"{label}: 보호대상 명칭이 비어 있습니다.")
        if category not in _ALLOWED_CLASSES:
            blockers.append(f"{label}: 보호대상 구분은 갑종/을종/환경수용체 중 하나로 확인해 주세요.")
        if not subtype:
            blockers.append(f"{label}: 보호대상 세부유형이 비어 있습니다.")
        if not address and not coordinate:
            blockers.append(f"{label}: 주소·위치 또는 좌표가 필요합니다.")
        if distance is None or distance < 0:
            blockers.append(f"{label}: 사업장 경계와 거리(m)를 0 이상의 GIS/현장 확정값으로 입력해 주세요.")
        elif distance > 500:
            blockers.append(
                f"{label}: 사업장 경계와 거리 {distance:g}m는 500m를 초과합니다. "
                "별지 제8호 500m 내 보호대상 목록 포함 여부를 다시 확인해 주세요."
            )
        if not evidence:
            blockers.append(f"{label}: GIS/현장 근거 식별자가 비어 있습니다.")

        identity = (_norm(name), category)
        if name and identity in seen:
            blockers.append(f"{label}: 동일 보호대상 명칭·구분이 중복되어 있습니다.")
        seen.add(identity)

        rows.append({
            "일련번호": len(rows) + 1,
            "보호대상 명칭": name,
            "보호대상 구분": category,
            "보호대상 종류": subtype,
            "주소·위치": address,
            "좌표": coordinate,
            "사업장 경계와 거리(m)": "" if distance is None else distance,
            "검색결과 거리(주소점 기준, 참고)": "" if search_distance is None else search_distance,
            "검색 출처·검색일": _clean(_row_value(raw, "검색 출처·검색일")),
            "500m 이내 여부": "예" if distance is not None and 0 <= distance <= 500 else "",
            "GIS/현장 근거": evidence,
        })

    if explicit_no_target and rows:
        blockers.append("500m 내 보호대상 없음으로 확인한 행과 보호대상 명세 행이 동시에 존재합니다.")
    if not explicit_no_target and not rows:
        blockers.append("500m 내 보호대상 명세가 없으며 '보호대상 없음'도 확정되지 않았습니다.")

    if explicit_no_target:
        messages.append("회사/GIS가 500m 내 보호대상 없음으로 확정한 경우 빈 목록을 허용합니다.")
    else:
        messages.append("보호대상 분류·거리·위치는 회사/GIS/현장 확정값만 사용합니다.")
    messages.append("프로그램은 주소만으로 주변 보호대상을 자동 추정하거나 새로 생성하지 않습니다.")

    return CAPForm8Data(
        rows=tuple(rows),
        blockers=tuple(dict.fromkeys(blockers)),
        messages=tuple(dict.fromkeys(messages)),
        no_protected_targets=explicit_no_target,
    )
