from __future__ import annotations

"""Prepare CAP Annex Form 10 without inventing a statutory capacity factor.

Annex Form 10 needs the containment-facility status, required capacity,
effective capacity and a review result.  The program may calculate effective
geometric capacity from confirmed dimensions, but it must not manufacture the
*required* capacity.  Required capacity and its legal/engineering basis remain
company/standard facts.  If they are absent, the row stays fail-closed.
"""

from dataclasses import dataclass
from collections.abc import Mapping
import math
import re
from typing import Any

from .cap_form9_engine import build_cap_form9_data
from .project import CONFIRMED_STATUSES, Stage2Project


NA_TOKENS = {"-", "해당없음", "해당 없음", "미해당", "n/a", "na", "not applicable"}
YES_TOKENS = {"예", "yes", "y", "적용", "해당", "true", "1"}
NO_TOKENS = {"아니오", "아니요", "no", "n", "false", "0", *NA_TOKENS}


@dataclass(frozen=True)
class CAPForm10Data:
    rows: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(self.rows) and not self.blockers


def _clean(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", _clean(value)).lower()


def _num(value: object) -> float | None:
    text = _clean(value).replace(",", "")
    if not text or text.lower() in NA_TOKENS:
        return None
    try:
        number = float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        number = float(match.group())
    return number if math.isfinite(number) else None


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{round(float(value), 8):g}"


def _row_value(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, "") and _clean(value):
            return value
    return ""


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


def _applicability(value: object) -> bool | None:
    text = _clean(value).lower()
    if not text:
        return None
    if text in YES_TOKENS:
        return True
    if text in NO_TOKENS:
        return False
    return None


def _effective_capacity(row: Mapping[str, Any]) -> tuple[float | None, list[str], str]:
    """Return effective m3, issues, and calculation basis."""
    issues: list[str] = []
    direct_raw = _row_value(row, "직접확인 유효용량(m3)", "유효용량(m3)", "유효용량")
    direct = _num(direct_raw)
    if _clean(direct_raw) and direct is None:
        issues.append("직접확인 유효용량(m3)의 숫자 형식을 확인해 주세요.")
    if direct is not None and direct < 0:
        issues.append("직접확인 유효용량(m3)은 0 이상이어야 합니다.")
        direct = None

    length_raw = _row_value(row, "내부 길이(m)", "길이(m)")
    width_raw = _row_value(row, "내부 폭(m)", "폭(m)")
    height_raw = _row_value(row, "유효높이(m)", "높이(m)")
    deduction_raw = _row_value(row, "내부 차감용적(m3)", "차감용적(m3)")

    dimension_values_present = any(_clean(v) for v in (length_raw, width_raw, height_raw, deduction_raw))
    geometric: float | None = None
    if dimension_values_present:
        length = _num(length_raw)
        width = _num(width_raw)
        height = _num(height_raw)
        deduction = _num(deduction_raw)

        if length is None or length <= 0:
            issues.append("유효용량 계산에 필요한 내부 길이(m)를 양수로 입력해 주세요.")
        if width is None or width <= 0:
            issues.append("유효용량 계산에 필요한 내부 폭(m)를 양수로 입력해 주세요.")
        if height is None or height <= 0:
            issues.append("유효용량 계산에 필요한 유효높이(m)를 양수로 입력해 주세요.")
        # Blank is not assumed to mean zero because internal equipment may
        # occupy containment volume.  A confirmed 0 is acceptable.
        if not _clean(deduction_raw):
            issues.append("내부 차감용적(m3)을 확인해 주세요. 차감이 없으면 0을 입력해 주세요.")
        elif deduction is None or deduction < 0:
            issues.append("내부 차감용적(m3)은 0 이상의 숫자로 입력해 주세요.")

        if (
            length is not None and length > 0
            and width is not None and width > 0
            and height is not None and height > 0
            and deduction is not None and deduction >= 0
        ):
            geometric = length * width * height - deduction
            if geometric < 0:
                issues.append("계산된 유효용량이 음수입니다. 치수와 차감용적을 확인해 주세요.")
                geometric = None

    if direct is not None and geometric is not None:
        tolerance = max(0.01, abs(direct) * 0.01)
        if abs(direct - geometric) > tolerance:
            issues.append(
                f"직접확인 유효용량({_fmt(direct)} m3)과 치수계산값({_fmt(geometric)} m3)이 "
                "1% 또는 0.01 m3 허용범위를 넘어 서로 다릅니다."
            )
        return direct, issues, "회사 확인 유효용량(치수계산값과 교차검증)"

    if direct is not None:
        return direct, issues, "회사 확인 유효용량"
    if geometric is not None:
        return geometric, issues, "내부 길이×폭×유효높이-내부 차감용적"
    if not dimension_values_present:
        issues.append(
            "유효용량을 확인할 수 없습니다. 직접확인 유효용량(m3) 또는 내부 치수와 차감용적을 입력해 주세요."
        )
    return None, issues, ""


def build_cap_form10_data(project: Stage2Project) -> CAPForm10Data:
    source_rows = _confirmed_rows(project, "cap.safety.dike_calculation")
    if not source_rows:
        return CAPForm10Data(
            (),
            ("확산방지설비 적용 여부 및 별지 제10호 계산자료가 확인되지 않았습니다.",),
            (),
        )

    form9 = build_cap_form9_data(project)
    raw_facilities = _confirmed_rows(project, "cap.facility.equipment_specs", "inventory.facilities")
    raw_facility_by_tag = {
        _clean(_row_value(row, "설비번호", "구분기호", "장치번호")): row
        for row in raw_facilities
        if _clean(_row_value(row, "설비번호", "구분기호", "장치번호"))
    }
    facility_by_tag = {
        _clean(row.get("구분기호")): dict(row)
        for row in form9.rows
        if _clean(row.get("구분기호"))
    }

    blockers: list[str] = []
    messages: list[str] = []
    output: list[dict[str, Any]] = []

    # A single explicit global N/A row is allowed where the company confirms
    # that Annex Form 10 containment facilities are not applicable.
    if len(source_rows) == 1:
        first_app = _applicability(_row_value(source_rows[0], "적용여부", "적용 여부"))
        target = _clean(_row_value(source_rows[0], "대상 설비번호", "구분기호", "설비번호"))
        if first_app is False and not target:
            output.append({
                "연번": 1,
                "설비형태": "-",
                "구분기호": "-",
                "장치·설비명": "-",
                "설계용량": "-",
                "설비종류": "-",
                "필요용량": "-",
                "유효용량": "-",
                "검토결과": "해당 없음",
                "비고": _clean(_row_value(source_rows[0], "비고")) or "회사 확인: 확산방지설비 적용대상 없음",
                "필요용량 근거": _clean(_row_value(source_rows[0], "필요용량 기준·근거", "필요용량 근거")),
                "유효용량 산정근거": "",
            })
            return CAPForm10Data(
                rows=tuple(output),
                blockers=(),
                messages=("확산방지설비 미적용 여부를 회사 확인값으로 반영했습니다.",),
            )

    for idx, row in enumerate(source_rows, start=1):
        applicable = _applicability(_row_value(row, "적용여부", "적용 여부"))
        target = _clean(_row_value(row, "대상 설비번호", "구분기호", "설비번호"))
        label = target or f"{idx}행"

        if applicable is None:
            blockers.append(f"{label}: 확산방지설비 적용여부를 예/아니오 또는 해당 없음으로 확인해 주세요.")
            continue

        if applicable is False:
            output.append({
                "연번": idx,
                "설비형태": _clean(_row_value(row, "설비형태")) or "-",
                "구분기호": target or "-",
                "장치·설비명": "-",
                "설계용량": "-",
                "설비종류": "-",
                "필요용량": "-",
                "유효용량": "-",
                "검토결과": "해당 없음",
                "비고": _clean(_row_value(row, "비고")) or "회사 확인: 해당 설비 확산방지설비 미적용",
                "필요용량 근거": _clean(_row_value(row, "필요용량 기준·근거", "필요용량 근거")),
                "유효용량 산정근거": "",
            })
            continue

        if not target:
            blockers.append(f"{label}: 적용대상 설비번호가 비어 있습니다.")
            continue

        facility = facility_by_tag.get(target)
        raw_facility = raw_facility_by_tag.get(target, {})
        if facility is None:
            blockers.append(f"{target}: 별지 제9호 장치·설비 목록에서 대상 설비번호를 찾지 못했습니다.")
            facility = {}

        source_facility_type = _clean(_row_value(raw_facility, "설비종류", "설비형태", "장치·설비 종류"))
        entered_facility_type = _clean(_row_value(row, "설비형태"))
        if source_facility_type and entered_facility_type and _norm(source_facility_type) != _norm(entered_facility_type):
            blockers.append(
                f"{target}: 확산방지설비 계산자료의 설비형태('{entered_facility_type}')와 "
                f"03_설비정보의 설비종류('{source_facility_type}')가 다릅니다."
            )
        facility_type = source_facility_type or entered_facility_type
        if not facility_type:
            blockers.append(f"{target}: 대상 취급시설의 설비형태를 확인할 수 없습니다.")

        containment_type = _clean(_row_value(row, "확산방지설비 종류", "설비종류"))
        if not containment_type:
            blockers.append(f"{target}: 확산방지설비 종류(방류벽·방지턱·트렌치 등)를 확인해 주세요.")

        required_raw = _row_value(row, "필요용량(m3)", "필요용량")
        required = _num(required_raw)
        if required is None or required <= 0:
            blockers.append(
                f"{target}: 필요용량(m3)은 적용 시설기준 또는 검토자료에서 확인된 양수값을 입력해 주세요."
            )
            required = None

        required_basis = _clean(_row_value(row, "필요용량 기준·근거", "필요용량 근거", "적용 기준"))
        if not required_basis:
            blockers.append(
                f"{target}: 필요용량의 적용 기준·근거가 없습니다. 프로그램이 임의 비율을 만들어 계산하지 않습니다."
            )

        effective, effective_issues, effective_basis = _effective_capacity(row)
        blockers.extend(f"{target}: {issue}" for issue in effective_issues)

        result = ""
        if required is not None and effective is not None:
            result = "적정" if effective >= required else "부족"

        output.append({
            "연번": idx,
            "설비형태": facility_type,
            "구분기호": target,
            "장치·설비명": _clean(facility.get("장치·설비명")),
            "설계용량": _clean(facility.get("설계용량(m3)")),
            "설비종류": containment_type,
            "필요용량": _fmt(required),
            "유효용량": _fmt(effective),
            "검토결과": result,
            "비고": _clean(_row_value(row, "비고")),
            "필요용량 근거": required_basis,
            "유효용량 산정근거": effective_basis,
        })

    messages.append(
        "유효용량은 회사 확인값 또는 내부 길이×폭×유효높이-내부 차감용적으로 계산하며, "
        "차감용적 공란을 임의로 0으로 보지 않습니다."
    )
    messages.append(
        "필요용량은 회사가 확인한 적용 시설기준·검토자료 값을 사용하며 일률적인 110% 등 임의 비율을 적용하지 않습니다."
    )
    messages.append("필요용량과 유효용량이 모두 확인된 경우에만 적정/부족을 자동판정합니다.")

    return CAPForm10Data(
        rows=tuple(output),
        blockers=tuple(dict.fromkeys(blockers)),
        messages=tuple(dict.fromkeys(messages)),
    )
