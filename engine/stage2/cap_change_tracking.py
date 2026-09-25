from __future__ import annotations

"""CAP 버전 간 변경점을 법정 변경서식에 연결하는 보조 엔진.

법적 판단을 새로 만들지 않는다. 저장된 적합/제출 버전과 현재 작업본의
회사 확인값을 비교하여 변경내역 후보를 만들고, 사용자가 확인한 뒤
별지 제2호 및 별지 제32호에 사용한다.
"""

from dataclasses import dataclass
import json
import math
import re
from typing import Any, Mapping

from .project import CONFIRMED_STATUSES, FieldRecord, Stage2Project
from . import versioning


@dataclass(frozen=True)
class CAPChangeSummary:
    base_version_id: str
    field_changes: tuple[versioning.FieldChange, ...]
    added_chemicals_before: str
    added_chemicals_after: str
    added_facilities_before: str
    added_facilities_after: str
    increased_amount_before: str
    increased_amount_after: str

    @property
    def changed(self) -> bool:
        return bool(self.field_changes)

    def form32_details(self) -> dict[str, dict[str, str]]:
        return {
            "유해화학물질추가": {"변경 전": self.added_chemicals_before, "변경 후": self.added_chemicals_after},
            "시설추가": {"변경 전": self.added_facilities_before, "변경 후": self.added_facilities_after},
            "취급저장량 증가": {"변경 전": self.increased_amount_before, "변경 후": self.increased_amount_after},
        }


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", str(value or "")).lower()


def _rows(fields: Mapping[str, FieldRecord], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        rec = fields.get(key)
        if rec is None or not isinstance(rec.value, list):
            continue
        rows = [dict(row) for row in rec.value if isinstance(row, Mapping)]
        if rows:
            return rows
    return []


def _row_value(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, ""):
            return value
    return ""


def _chemical_key(row: Mapping[str, Any]) -> str:
    cas = str(_row_value(row, "CAS 번호", "CAS No.", "화학물질식별번호") or "").strip()
    if cas:
        return "cas:" + cas
    return "name:" + _norm(_row_value(row, "물질명", "유해화학물질명", "제품명"))


def _chemical_label(row: Mapping[str, Any]) -> str:
    name = str(_row_value(row, "물질명", "유해화학물질명", "제품명") or "").strip()
    cas = str(_row_value(row, "CAS 번호", "CAS No.", "화학물질식별번호") or "").strip()
    if name and cas:
        return f"{name} ({cas})"
    return name or cas


def _facility_key(row: Mapping[str, Any]) -> str:
    tag = str(_row_value(row, "설비번호", "구분기호", "장치번호") or "").strip()
    if tag:
        return "tag:" + _norm(tag)
    return "name:" + _norm(_row_value(row, "설비명", "취급시설", "장치·설비명"))


def _facility_label(row: Mapping[str, Any]) -> str:
    tag = str(_row_value(row, "설비번호", "구분기호", "장치번호") or "").strip()
    name = str(_row_value(row, "설비명", "취급시설", "장치·설비명") or "").strip()
    if tag and name:
        return f"{tag} {name}"
    return tag or name


def _number(value: object) -> float | None:
    text = str(value or "").replace(",", "").strip()
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


def _amount_kg(row: Mapping[str, Any]) -> float | None:
    direct = _number(_row_value(row, "최대보유량(kg)"))
    if direct is not None:
        return direct
    value = _number(_row_value(row, "최대보유량", "취급량"))
    unit = _norm(_row_value(row, "최대보유량 단위", "취급량 단위", "단위"))
    if value is None:
        return None
    if unit in {"ton", "t", "톤"}:
        return value * 1000.0
    if unit in {"g", "그램"}:
        return value / 1000.0
    if unit in {"kg", "킬로그램"}:
        return value
    return None


def _fmt_kg(value: float | None) -> str:
    if value is None:
        return ""
    if value >= 1000:
        return f"{value / 1000:g} ton"
    return f"{value:g} kg"


def summarize_changes(project: Stage2Project, base_version_id: str) -> CAPChangeSummary:
    before = versioning.load_version_fields(project.project_id, base_version_id)
    after = project.fields

    before_chems = {_chemical_key(row): row for row in _rows(before, "inventory.chemicals", "cap.chemical.details") if _chemical_key(row)}
    after_chems = {_chemical_key(row): row for row in _rows(after, "inventory.chemicals", "cap.chemical.details") if _chemical_key(row)}
    added_chem_keys = [key for key in after_chems if key not in before_chems]

    before_fac = {_facility_key(row): row for row in _rows(before, "cap.workspace.facilities", "inventory.facilities", "cap.facility.equipment_specs") if _facility_key(row)}
    after_fac = {_facility_key(row): row for row in _rows(after, "cap.workspace.facilities", "inventory.facilities", "cap.facility.equipment_specs") if _facility_key(row)}
    added_fac_keys = [key for key in after_fac if key not in before_fac]

    increases: list[tuple[str, str, str]] = []
    for key in sorted(set(before_fac).intersection(after_fac)):
        old_amount, new_amount = _amount_kg(before_fac[key]), _amount_kg(after_fac[key])
        if old_amount is None or new_amount is None or new_amount <= old_amount:
            continue
        label = _facility_label(after_fac[key]) or _facility_label(before_fac[key])
        increases.append((label, _fmt_kg(old_amount), _fmt_kg(new_amount)))

    before_chem_text = ", ".join(_chemical_label(before_chems[key]) for key in before_chems) if added_chem_keys else ""
    after_chem_text = ", ".join(_chemical_label(after_chems[key]) for key in after_chems) if added_chem_keys else ""
    before_fac_text = ", ".join(_facility_label(before_fac[key]) for key in before_fac) if added_fac_keys else ""
    after_fac_text = ", ".join(_facility_label(after_fac[key]) for key in after_fac) if added_fac_keys else ""

    return CAPChangeSummary(
        base_version_id=base_version_id,
        field_changes=tuple(versioning.diff_versions(project, base_version_id)),
        added_chemicals_before=before_chem_text,
        added_chemicals_after=after_chem_text,
        added_facilities_before=before_fac_text,
        added_facilities_after=after_fac_text,
        increased_amount_before="; ".join(f"{label}: {old}" for label, old, _new in increases),
        increased_amount_after="; ".join(f"{label}: {new}" for label, _old, new in increases),
    )


def _change_type(key: str) -> str:
    if key.startswith(("inventory.chemicals", "cap.chemical.")):
        return "㈑ 취급물질 변경"
    if key.startswith(("cap.notification.", "cap.community.")):
        return "㈒ 고지계획 변경"
    # Facility, safety, process, staffing, and other data diffs do not reveal
    # whether the legal class is size, location, material, update, or other.
    # Leave the category for the operator to confirm against the actual change.
    return ""


def _short(value: Any, limit: int = 180) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def proposed_form2_rows(
    project: Stage2Project,
    base_version_id: str,
    *,
    change_date: str,
    person: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for change in versioning.diff_versions(project, base_version_id):
        arrow = f"{_short(change.old)} → {_short(change.new)}"
        rows.append({
            "일자": change_date,
            "변경항목": change.label or change.key,
            "변경의 종류": _change_type(change.key),
            "변경 내용(변경전 → 변경후)": arrow,
            # The field diff cannot decide Article 11 CAP submission, permit
            # change-report, or prior-permission applicability. Keep it blank.
            "후속조치": "",
            "담당자": person,
        })
    return rows


def form2_change_candidates(project: Stage2Project, base_version_id: str) -> list[dict[str, str]]:
    """Compare supported, confirmed CAP facts; never infer a legal follow-up.

    A missing source in either version cannot prove an addition or increase.
    Facility design capacity and maximum holding are separate facts and units
    must match before a numeric comparison is made.
    """
    before = versioning.load_version_fields(project.project_id, base_version_id)
    after = project.fields
    candidates: list[dict[str, str]] = []

    def paired_rows(*keys: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        for key in keys:
            old, new = before.get(key), after.get(key)
            if (old and new and old.status in CONFIRMED_STATUSES and new.status in CONFIRMED_STATUSES
                    and isinstance(old.value, list) and isinstance(new.value, list)):
                return _rows(before, key), _rows(after, key)
        return None

    chemicals = paired_rows("inventory.chemicals", "cap.chemical.details")
    if chemicals:
        old_rows, new_rows = chemicals
        old_keys = {_chemical_key(row) for row in old_rows}
        for row in new_rows:
            key = _chemical_key(row)
            if key and key not in old_keys:
                candidates.append({
                    "제목": "유해화학물질 추가",
                    "변경항목": "유해화학물질 목록 및 명세",
                    "변경의 종류": "㈑ 취급물질 변경",
                    "변경 전": "기존 목록에 없음",
                    "변경 후": _chemical_label(row),
                    "확인자료": "이전 제출본·현재 물질목록·공급자 SDS",
                })

    facilities = paired_rows("cap.workspace.facilities", "inventory.facilities", "cap.facility.equipment_specs")
    if facilities:
        old_rows, new_rows = facilities
        old_by_key = {_facility_key(row): row for row in old_rows if _facility_key(row)}
        for row in new_rows:
            key = _facility_key(row)
            if not key:
                continue
            label = _facility_label(row)
            if key not in old_by_key:
                candidates.append({
                    "제목": "신규 시설 확인",
                    "변경항목": "장치·설비 목록 및 명세",
                    "변경의 종류": "",  # 신설만으로 규모·위치 변경을 단정하지 않는다.
                    "변경 전": "기존 목록에 없음",
                    "변경 후": label,
                    "확인자료": "이전 제출본·현재 설비목록·설비배치도",
                })
                continue
            old_row = old_by_key[key]
            old_capacity = _number(_row_value(old_row, "용량", "설계용량"))
            new_capacity = _number(_row_value(row, "용량", "설계용량"))
            old_unit = _norm(_row_value(old_row, "용량단위", "설계용량 단위"))
            new_unit = _norm(_row_value(row, "용량단위", "설계용량 단위"))
            if (old_capacity is not None and new_capacity is not None and old_capacity >= 0
                    and old_unit and old_unit == new_unit and new_capacity > old_capacity):
                candidates.append({
                    "제목": "시설 설계용량 증가",
                    "변경항목": "장치·설비 목록 및 명세",
                    "변경의 종류": "㈎ 시설규모 변경",
                    "변경 전": f"{label}: {old_capacity:g} {_row_value(old_row, '용량단위', '설계용량 단위')}",
                    "변경 후": f"{label}: {new_capacity:g} {_row_value(row, '용량단위', '설계용량 단위')}",
                    "확인자료": "이전 제출본·설비목록·P&ID·설비배치도",
                })
            old_holding, new_holding = _amount_kg(old_row), _amount_kg(row)
            if old_holding is not None and new_holding is not None and new_holding > old_holding:
                candidates.append({
                    "제목": "시설별 최대보유량 증가",
                    "변경항목": "취급시설 개요",
                    "변경의 종류": "",  # 보유량 증가만으로 용량 증가를 단정하지 않는다.
                    "변경 전": f"{label}: {_fmt_kg(old_holding)}",
                    "변경 후": f"{label}: {_fmt_kg(new_holding)}",
                    "확인자료": "별지 제1호·설비별 보유량 산출자료·이전 제출본",
                })
    return candidates
