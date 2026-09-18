from __future__ import annotations

"""Prepare CAP Annex Form 9 with statutory units and granular completeness checks."""

from dataclasses import dataclass
from collections.abc import Mapping
import math
import re
from typing import Any

from .cap_form1_engine import mass_to_ton, volume_to_m3
from .project import CONFIRMED_STATUSES, Stage2Project


NA_TOKENS = {"-", "해당없음", "해당 없음", "n/a", "na", "not applicable"}


@dataclass(frozen=True)
class CAPForm9Data:
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


def _is_na(value: object) -> bool:
    return _clean(value).lower() in NA_TOKENS


def _num(value: object) -> float | None:
    text = _clean(value).replace(",", "")
    if not text or _is_na(text):
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


def _pressure_mpa(value: object) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    if _is_na(raw):
        return "-"
    number = _num(raw)
    if number is None:
        return ""
    n = raw.lower().replace(" ", "")
    if "kpa" in n:
        number /= 1000.0
    elif "bar" in n:
        number /= 10.0
    # Numeric values or MPa-labelled values are interpreted as MPa because the
    # Stage 2 column and statutory Form 9 header both use MPa.
    return _fmt(number)


def _temperature_c(value: object) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    if _is_na(raw):
        return "-"
    return _fmt(_num(raw))


def _capacity_m3(row: Mapping[str, Any]) -> tuple[str, str | None]:
    explicit = _row_value(row, "설계용량(m3)", "CAP 설계용량(m3)")
    if _clean(explicit):
        if _is_na(explicit):
            return "-", None
        value = _num(explicit)
        return (_fmt(value), None) if value is not None else ("", "설계용량(m3)의 숫자 형식을 확인해 주세요.")

    amount = _row_value(row, "용량", "설계용량")
    unit = _row_value(row, "용량단위", "설계용량 단위")
    if _is_na(amount) or _is_na(unit):
        return "-", None
    if not _clean(amount):
        return "", "설계용량이 비어 있습니다. 해당하지 않으면 '해당 없음'을 명시해 주세요."
    normalized_unit = _clean(unit).lower().replace(" ", "")
    if "/h" in normalized_unit or "h-1" in normalized_unit:
        # A flow-rate capacity is not a vessel design volume.
        return "-", None
    value = volume_to_m3(amount, unit)
    if value is None:
        return "", f"설계용량 단위 '{_clean(unit) or '(미입력)'}'를 m3로 환산할 수 없습니다."
    return _fmt(value), None


def _holding_ton(row: Mapping[str, Any]) -> tuple[str, str | None]:
    explicit = _row_value(row, "취급량(ton)")
    if _clean(explicit):
        if _is_na(explicit):
            return "-", None
        value = _num(explicit)
        return (_fmt(value), None) if value is not None else ("", "취급량(ton)의 숫자 형식을 확인해 주세요.")

    kg_value = _row_value(row, "최대보유량(kg)")
    if _clean(kg_value):
        value = mass_to_ton(kg_value, "kg")
        return (_fmt(value), None) if value is not None else ("", "최대보유량(kg)을 ton으로 환산할 수 없습니다.")

    value = _row_value(row, "취급량", "최대보유량")
    unit = _row_value(row, "취급량 단위", "최대보유량 단위", "단위")
    if _is_na(value) or _is_na(unit):
        return "-", None
    if not _clean(value):
        return "", "취급량/최대보유량이 비어 있습니다. 해당하지 않으면 '해당 없음'을 명시해 주세요."
    ton = mass_to_ton(value, unit)
    if ton is None:
        return "", f"취급량 단위 '{_clean(unit) or '(미입력)'}'를 ton으로 환산할 수 없습니다."
    return _fmt(ton), None


def _connection_mm(row: Mapping[str, Any]) -> tuple[str, str | None]:
    raw = _row_value(
        row,
        "최대 연결구 크기(mm)",
        "연결구 크기(mm)",
        "연결구 크기",
        "호칭경",
    )
    if not _clean(raw):
        return "", "최대 연결구 크기(mm)가 비어 있습니다. P&ID/배관명세로 확인하거나 해당 없음을 명시해 주세요."
    if _is_na(raw):
        return "-", None
    value = _num(raw)
    if value is None:
        return "", "최대 연결구 크기(mm)의 숫자 형식을 확인해 주세요."
    return _fmt(value), None


def _chemical_index(project: Stage2Project) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = _confirmed_rows(project, "cap.chemical.details", "inventory.chemicals")
    by_name: dict[str, dict[str, Any]] = {}
    by_cas: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = _norm(_row_value(row, "물질명", "유해화학물질명", "제품명"))
        cas = _clean(_row_value(row, "CAS 번호", "CAS No.", "화학물질식별번호"))
        if name:
            by_name.setdefault(name, row)
        if cas:
            by_cas.setdefault(cas, row)
    return by_name, by_cas


def build_cap_form9_data(project: Stage2Project) -> CAPForm9Data:
    facilities = _confirmed_rows(project, "cap.facility.equipment_specs", "inventory.facilities")
    if not facilities:
        return CAPForm9Data((), ("장치·설비 목록이 없어 별지 제9호를 작성할 수 없습니다.",), ())

    by_name, by_cas = _chemical_index(project)
    blockers: list[str] = []
    messages: list[str] = []
    out: list[dict[str, Any]] = []

    for index, facility in enumerate(facilities, start=1):
        tag = _clean(_row_value(facility, "설비번호", "구분기호", "장치번호"))
        equipment_name = _clean(_row_value(facility, "설비명", "장치·설비명", "장치명"))
        material = _clean(_row_value(facility, "취급물질", "물질명"))
        facility_cas = _clean(_row_value(facility, "CAS 번호", "CAS No."))
        chem = by_cas.get(facility_cas) if facility_cas else None
        if chem is None and material:
            chem = by_name.get(_norm(material))

        label = tag or equipment_name or f"{index}행"
        if not tag:
            blockers.append(f"{label}: 설비 식별번호가 비어 있습니다.")
        if not equipment_name:
            blockers.append(f"{label}: 장치·설비명이 비어 있습니다.")
        if not material:
            blockers.append(f"{label}: 취급물질이 비어 있습니다.")

        cas = _clean(_row_value(chem or {}, "CAS 번호", "CAS No.", "화학물질식별번호"))
        state = _clean(_row_value(chem or {}, "물리적 상태", "물질상태"))
        content = _clean(_row_value(chem or {}, "함량(%)", "함량", "농도(%)"))
        if material and chem is None:
            blockers.append(f"{label}: 취급물질 '{material}'을 화학물질 목록의 CAS/함량 정보와 연결하지 못했습니다.")
        elif chem is not None:
            if not cas:
                blockers.append(f"{label}: 취급물질의 CAS 번호가 비어 있습니다.")
            if not state:
                blockers.append(f"{label}: 취급물질의 물질상태가 비어 있습니다.")
            if not content:
                blockers.append(f"{label}: 취급물질의 함량(%)이 비어 있습니다.")

        connection, connection_error = _connection_mm(facility)
        capacity, capacity_error = _capacity_m3(facility)
        holding, holding_error = _holding_ton(facility)
        for error in (connection_error, capacity_error, holding_error):
            if error:
                blockers.append(f"{label}: {error}")

        design_pressure = _pressure_mpa(_row_value(facility, "설계압력"))
        operating_pressure = _pressure_mpa(_row_value(facility, "운전압력"))
        design_temperature = _temperature_c(_row_value(facility, "설계온도"))
        operating_temperature = _temperature_c(_row_value(facility, "운전온도"))
        for field_label, value in (
            ("설계압력", design_pressure),
            ("운전압력", operating_pressure),
            ("설계온도", design_temperature),
            ("운전온도", operating_temperature),
        ):
            if not value:
                blockers.append(f"{label}: {field_label}이 비어 있습니다. 해당하지 않으면 '해당 없음'을 명시해 주세요.")

        out.append({
            "연번": index,
            "구분기호": tag,
            "장치·설비명": equipment_name,
            "취급물질": material,
            "CAS No.": cas,
            "물질상태": state,
            "함량(%)": content,
            "연결구 크기(mm)": connection,
            "압력(MPa)-설계": design_pressure,
            "압력(MPa)-운전": operating_pressure,
            "온도(℃)-설계": design_temperature,
            "온도(℃)-운전": operating_temperature,
            "설계용량(m3)": capacity,
            "취급량(ton)": holding,
            "비고": _clean(_row_value(facility, "비고", "P&ID 번호")),
        })

    messages.append("별지 제9호의 최대보유량(kg)은 ton으로, L 단위 설계용량은 m3로 정규화합니다.")
    messages.append("유량단위(m3/h 등)는 설계용량(m3) 칸에 복사하지 않고 해당 없음(-)으로 처리합니다.")
    return CAPForm9Data(
        rows=tuple(out),
        blockers=tuple(dict.fromkeys(blockers)),
        messages=tuple(dict.fromkeys(messages)),
    )
