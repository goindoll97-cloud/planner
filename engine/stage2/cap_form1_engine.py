from __future__ import annotations

"""Prepare CAP Annex Form 1 from confirmed Stage 2 facts and Stage 1 legal rules.

The module intentionally reuses the Stage 1 CAP quantity-rule screen instead of
maintaining a second legal table.  Company quantities are normalized to ton and
are never used to invent a legal classification when the approved rule screen
cannot resolve the material.
"""

from dataclasses import dataclass
from collections.abc import Mapping
import math
import re
from typing import Any

import pandas as pd

from engine.cap_holding_screen import screen_facility_stage
from engine.inventory import IntakeData

from .project import CONFIRMED_STATUSES, Stage2Project


@dataclass(frozen=True)
class CAPForm1Data:
    facility_rows: tuple[dict[str, Any], ...]
    chemical_rows: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]
    legal_lookup_ready: bool

    @property
    def ready(self) -> bool:
        return self.legal_lookup_ready and not self.blockers and bool(self.chemical_rows)


def _clean(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


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


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", _clean(value)).lower()


def _row_value(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, "") and _clean(value):
            return value
    return ""


def _confirmed_rows(project: Stage2Project, *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        record = project.get_field(key)
        if record is None or record.status not in CONFIRMED_STATUSES:
            continue
        if isinstance(record.value, list):
            rows = [dict(row) for row in record.value if isinstance(row, Mapping)]
            if rows:
                return rows
    return []


def mass_to_ton(value: object, unit: object) -> float | None:
    amount = _num(value)
    if amount is None or amount < 0:
        return None
    norm = _clean(unit).lower().replace(" ", "")
    if norm in {"kg", "킬로그램"}:
        return amount / 1000.0
    if norm in {"ton", "t", "톤"}:
        return amount
    if norm in {"g", "그램"}:
        return amount / 1_000_000.0
    return None


def volume_to_m3(value: object, unit: object) -> float | None:
    amount = _num(value)
    if amount is None or amount < 0:
        return None
    norm = _clean(unit).lower().replace(" ", "")
    if norm in {"m3", "m³", "㎥"}:
        return amount
    if norm in {"l", "liter", "litre", "리터"}:
        return amount / 1000.0
    return None


def _fmt_num(value: float | None) -> str:
    if value is None:
        return ""
    rounded = round(float(value), 8)
    if rounded == 0:
        return "0"
    return f"{rounded:g}"


def _material_class(hit: Mapping[str, Any]) -> str:
    source = _clean(hit.get("source_key"))
    if source == "CAP_QTY_APP3":
        return "사고대비물질"
    if source == "CAP_QTY_APP2":
        category = _clean(hit.get("hazard_category"))
        return category or "별표 2 규정대상"
    return source or ""


def _quantity_band(value: float | None, lower: float | None, upper: float | None) -> str:
    if value is None:
        return ""
    if upper is not None and value >= upper:
        return "상위 규정수량 이상"
    if lower is not None and value >= lower:
        return "하위 이상·상위 미만"
    return "하위 규정수량 미만"


def _chemical_identity_rows(project: Stage2Project) -> list[dict[str, Any]]:
    return _confirmed_rows(project, "inventory.chemicals", "cap.chemical.details")


def _facility_source_rows(project: Stage2Project) -> list[dict[str, Any]]:
    return _confirmed_rows(project, "inventory.facilities", "cap.facility.equipment_specs")


def _adapt_chemicals_for_stage1(chemicals: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in chemicals:
        adapted = {
            "제품명": _row_value(row, "물질명", "유해화학물질명", "제품명"),
            "CAS No.": _row_value(row, "CAS 번호", "CAS No.", "화학물질식별번호"),
            "함량(%)": _row_value(row, "함량(%)", "함량", "농도(%)"),
        }
        state = _row_value(row, "상온·상압 액체 여부(해당 시)", "상온·상압 액체 여부")
        if state:
            adapted["상온·상압 액체 여부(해당 시)"] = state
        rows.append(adapted)
    return pd.DataFrame(rows)


def _chemical_index(chemicals: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    by_name: dict[str, int] = {}
    by_cas: dict[str, int] = {}
    for idx, row in enumerate(chemicals, start=1):
        name = _norm(_row_value(row, "물질명", "유해화학물질명", "제품명"))
        cas = _clean(_row_value(row, "CAS 번호", "CAS No.", "화학물질식별번호"))
        if name:
            by_name.setdefault(name, idx)
        if cas:
            by_cas.setdefault(cas, idx)
    return by_name, by_cas


def _facility_holding_ton(row: Mapping[str, Any]) -> float | None:
    # The integrated Stage 2 equipment sheet explicitly labels this field kg.
    value = _row_value(row, "최대보유량(kg)")
    if _clean(value):
        return mass_to_ton(value, "kg")

    value = _row_value(row, "취급량", "최대보유량")
    unit = _row_value(row, "취급량 단위", "최대보유량 단위", "단위")
    return mass_to_ton(value, unit)


def _chemical_holding_ton(row: Mapping[str, Any]) -> float | None:
    value = _row_value(row, "최대보유량", "최대보유량(kg)")
    unit = _row_value(row, "단위", "최대보유량 단위")
    if _clean(unit):
        return mass_to_ton(value, unit)
    if _clean(_row_value(row, "최대보유량(kg)")):
        return mass_to_ton(value, "kg")
    return None


def build_cap_form1_data(project: Stage2Project) -> CAPForm1Data:
    chemicals = _chemical_identity_rows(project)
    facilities = _facility_source_rows(project)
    blockers: list[str] = []
    messages: list[str] = []

    if not chemicals:
        return CAPForm1Data((), (), ("화학물질 목록이 없어 별지 제1호를 작성할 수 없습니다.",), (), False)

    intake = IntakeData(
        business={},
        chemicals=_adapt_chemicals_for_stage1(chemicals),
        documents={},
        facilities=pd.DataFrame(),
    )
    screen = screen_facility_stage(intake)
    if not screen.ready:
        blockers.extend(screen.blockers or ["CAP 규정수량 승인 DB를 확인할 수 없습니다."])
    else:
        blockers.extend(screen.blockers)
    messages.extend(screen.messages)

    by_name, by_cas = _chemical_index(chemicals)
    facility_rows: list[dict[str, Any]] = []
    holding_by_row: dict[int, float] = {}

    default_unit_plant = ""
    rec = project.get_field("cap.business.unit_plant_name")
    if rec and rec.status in CONFIRMED_STATUSES:
        default_unit_plant = _clean(rec.value)
    if not default_unit_plant:
        default_unit_plant = _clean(project.site_name)

    for facility in facilities:
        material = _clean(_row_value(facility, "취급물질", "물질명"))
        cas = _clean(_row_value(facility, "CAS 번호", "CAS No."))
        chem_no = by_cas.get(cas) if cas else None
        if chem_no is None and material:
            chem_no = by_name.get(_norm(material))
        chem = chemicals[chem_no - 1] if chem_no else {}
        if not material:
            material = _clean(_row_value(chem, "물질명", "유해화학물질명", "제품명"))
        if not cas:
            cas = _clean(_row_value(chem, "CAS 번호", "CAS No.", "화학물질식별번호"))
        pct = _row_value(chem, "함량(%)", "함량", "농도(%)")
        ton = _facility_holding_ton(facility)
        if chem_no and ton is not None:
            holding_by_row[chem_no] = holding_by_row.get(chem_no, 0.0) + ton
        elif material and ton is None:
            blockers.append(f"{material}: 설비별 최대보유량의 질량단위를 ton으로 환산할 수 없습니다.")

        cap = _row_value(facility, "용량", "설계용량")
        cap_unit = _row_value(facility, "용량단위", "설계용량 단위")
        capacity_m3 = volume_to_m3(cap, cap_unit)
        design_capacity = _fmt_num(capacity_m3)
        if _clean(cap) and not design_capacity:
            blockers.append(
                f"{_clean(_row_value(facility, '설비명', '취급시설')) or material}: "
                "설계용량을 m3로 환산할 수 없는 단위입니다."
            )
        facility_rows.append({
            "단위공장": _row_value(facility, "단위공장·공정", "단위공장", "공정") or default_unit_plant,
            "유해화학물질": material,
            "CAS No.": cas,
            "함량(%)": pct,
            "구분기호": _row_value(facility, "설비번호", "구분기호", "장치번호"),
            "취급시설": _row_value(facility, "설비명", "취급시설", "장치·설비명"),
            "설계용량(m3)": design_capacity,
            "취급량(ton)": _fmt_num(ton),
            "산정근거": "Stage2 회사 확정 설비별 최대보유량을 ton으로 정규화",
        })

    hits_by_row: dict[int, list[dict[str, Any]]] = {}
    for hit in screen.legal_hits:
        row_no = int(hit.get("row_no") or 0)
        if row_no > 0:
            hits_by_row.setdefault(row_no, []).append(dict(hit))

    chemical_rows: list[dict[str, Any]] = []
    for row_no, chem in enumerate(chemicals, start=1):
        name = _clean(_row_value(chem, "물질명", "유해화학물질명", "제품명"))
        cas = _clean(_row_value(chem, "CAS 번호", "CAS No.", "화학물질식별번호"))
        holding = holding_by_row.get(row_no)
        basis = "설비별 최대보유량 합산"
        if holding is None:
            holding = _chemical_holding_ton(chem)
            basis = "회사 화학물질표 최대보유량"
        if holding is None:
            blockers.append(f"{name or cas or f'{row_no}행'}: 사업장 최대보유량을 ton으로 환산할 수 없습니다.")

        hits = hits_by_row.get(row_no, [])
        if not hits:
            chemical_rows.append({
                "물질명": name,
                "CAS No.": cas,
                "물질구분": "",
                "사업장 내 최대보유량(ton)": _fmt_num(holding),
                "작성수준": project.cap_group,
                "하위규정수량(ton)": "",
                "상위규정수량(ton)": "",
                "규정수량 비교": "",
                "산정근거": basis,
            })
            if screen.ready and cas:
                blockers.append(
                    f"{name or cas}: 별표 3→별표 2 직접 규칙에서 규정수량을 확정하지 못했습니다. "
                    "별표 1 유해·위험성 그룹 또는 포괄 규제범위 확인이 필요합니다."
                )
            continue

        for hit in hits:
            lower = _num(hit.get("lower_quantity_ton"))
            upper = _num(hit.get("upper_quantity_ton"))
            chemical_rows.append({
                "물질명": name or _clean(hit.get("legal_substance")),
                "CAS No.": cas or _clean(hit.get("cas")),
                "물질구분": _material_class(hit),
                "사업장 내 최대보유량(ton)": _fmt_num(holding),
                "작성수준": project.cap_group,
                "하위규정수량(ton)": _fmt_num(lower),
                "상위규정수량(ton)": _fmt_num(upper),
                "규정수량 비교": _quantity_band(holding, lower, upper),
                "산정근거": basis,
                "법령DB": _clean(hit.get("source_key")),
                "법령항목": _clean(hit.get("item_no")),
                "법령물질명": _clean(hit.get("legal_substance")),
            })

    if not facilities:
        messages.append("설비별 자료가 없어 화학물질표의 최대보유량을 보조값으로 사용합니다.")

    if project.stage1_source_fingerprint:
        messages.append("Stage 1 회사 입력자료와 법적 판정에서 승계된 프로젝트입니다.")
    else:
        blockers.append(
            "Stage 1 판정과 연결되지 않은 직접 시작 프로젝트입니다. 별지 제1호의 최대보유량이 "
            "법정 산정기준에 따른 값인지 최종 제출 전에 확인해야 합니다."
        )

    return CAPForm1Data(
        facility_rows=tuple(facility_rows),
        chemical_rows=tuple(chemical_rows),
        blockers=tuple(dict.fromkeys(blockers)),
        messages=tuple(dict.fromkeys(messages)),
        legal_lookup_ready=bool(screen.ready),
    )
