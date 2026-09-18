from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

from .project import CONFIRMED_STATUSES, Stage2Project


@dataclass(frozen=True)
class CAPFormReadiness:
    form_no: int
    form_name: str
    blockers: tuple[str, ...]
    messages: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.blockers


def _record(project: Stage2Project, key: str):
    rec = project.get_field(key)
    if rec is None or rec.status not in CONFIRMED_STATUSES:
        return None
    if rec.value in (None, "", [], {}):
        return None
    return rec


def _has(project: Stage2Project, key: str) -> bool:
    return _record(project, key) is not None


def _rows(project: Stage2Project, *keys: str) -> list[Mapping[str, Any]]:
    for key in keys:
        rec = _record(project, key)
        if rec is None or not isinstance(rec.value, list):
            continue
        rows = [dict(row) for row in rec.value if isinstance(row, Mapping)]
        if rows:
            return rows
    return []


def _summary_rows(project: Stage2Project, key: str) -> list[Mapping[str, Any]]:
    rec = _record(project, key)
    if rec is None:
        return []
    if isinstance(rec.value, Mapping):
        return [dict(rec.value)]
    if isinstance(rec.value, list):
        return [dict(row) for row in rec.value if isinstance(row, Mapping)]
    return []


def _norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _row_value(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, ""):
            return value
    return ""


def _residents_state_available(project: Stage2Project) -> bool:
    if _has(project, "cap.business.residents_in_overall_range"):
        return True
    for row in _summary_rows(project, "cap.offsite.overall_impact_summary"):
        if _row_value(
            row,
            "총괄영향범위 내 거주민수",
            "거주민수",
            "총괄 거주민수",
        ) not in (None, ""):
            return True
    return False


def _writing_level_available(project: Stage2Project) -> bool:
    if str(project.cap_group or "").strip() in {"1군", "2군"}:
        return True
    rec = _record(project, "cap.business.writing_level")
    if rec is None:
        return False
    value = str(rec.value or "").strip()
    return "1군" in value or "2군" in value


def _unit_plant_available(project: Stage2Project) -> bool:
    return _has(project, "cap.business.unit_plant_name") or bool(str(project.site_name or "").strip())


def _writer_available(project: Stage2Project) -> bool:
    return _has(project, "cap.business.writer_name") or _has(project, "cap.business.writer_info")


def build_cap_form3_readiness(project: Stage2Project) -> CAPFormReadiness:
    blockers: list[str] = []

    if not str(project.company_name or "").strip():
        blockers.append("사업장명이 확인되지 않았습니다.")
    if not _unit_plant_available(project):
        blockers.append("단위공장명이 확인되지 않았습니다.")
    for key, label in (
        ("cap.business.registration_no", "사업자등록번호"),
        ("cap.business.representative", "대표자"),
        ("business.address", "사업장 주소"),
        ("cap.business.industrial_complex", "산업단지 여부·명칭"),
        ("cap.business.contact", "대표전화"),
        ("cap.business.submission_type", "제출구분"),
        ("cap.business.submission_reason", "제출 사유(최초/부적합 등)"),
        ("cap.business.joint_emergency_plan", "공동비상대응계획 수립 여부"),
        ("cap.business.other_system_review", "유사제도 심사결과 활용 여부"),
        ("cap.business.recent_accident", "최근 3년간 화학사고 발생 여부"),
        ("cap.business.writer_contact", "담당자 연락처"),
        ("cap.business.writer_email", "담당자 메일주소"),
    ):
        if not _has(project, key):
            blockers.append(f"{label}가 확인되지 않았습니다.")

    if not _writing_level_available(project):
        blockers.append("작성수준(1군/2군)이 확인되지 않았습니다.")
    if not _residents_state_available(project):
        blockers.append("총괄영향범위 내 주민 여부를 확인할 자료가 없습니다.")
    if not _writer_available(project):
        blockers.append("화학사고예방관리계획서 작성자가 확인되지 않았습니다.")

    return CAPFormReadiness(
        form_no=3,
        form_name="사업장 일반정보",
        blockers=tuple(blockers),
        messages=("별지 제3호의 사업장·제출·담당자 핵심정보를 확인했습니다.",) if not blockers else (),
    )


def _common_facility_blockers(project: Stage2Project) -> list[str]:
    blockers: list[str] = []
    if not _has(project, "process.description"):
        blockers.append("공정개요가 확인되지 않았습니다.")
    if not _rows(project, "inventory.facilities", "cap.facility.equipment_specs"):
        blockers.append("장치·설비 목록이 확인되지 않았습니다.")
    if not _has(project, "cap.basic.loading_transport"):
        blockers.append("입·출하 및 운반시설 정보가 확인되지 않았습니다.")
    if not _rows(project, "inventory.chemicals", "cap.chemical.details"):
        blockers.append("유해화학물질 목록이 확인되지 않았습니다.")
    return blockers


def build_cap_form4_readiness(project: Stage2Project) -> CAPFormReadiness:
    blockers = _common_facility_blockers(project)
    if not _has(project, "cap.basic.total_facility_overview"):
        blockers.insert(0, "총괄 취급시설 구성정보가 확인되지 않았습니다.")
    return CAPFormReadiness(
        form_no=4,
        form_name="총괄 취급시설 개요",
        blockers=tuple(blockers),
        messages=("별지 제4호의 총괄 취급시설 개요 작성자료를 확인했습니다.",) if not blockers else (),
    )


def build_cap_form5_readiness(project: Stage2Project) -> CAPFormReadiness:
    blockers = _common_facility_blockers(project)
    if not _has(project, "cap.basic.unit_facility_overview"):
        blockers.insert(0, "단위공장 취급시설 구성정보가 확인되지 않았습니다.")
    return CAPFormReadiness(
        form_no=5,
        form_name="세부 취급시설 개요",
        blockers=tuple(blockers),
        messages=("별지 제5호의 세부 취급시설 개요 작성자료를 확인했습니다.",) if not blockers else (),
    )
