from __future__ import annotations

"""Prepare CAP Annex Form 11 from confirmed fixed detector specifications.

Form 11 is for fixed hazardous-material detection facilities. Installation
form (fixed/portable) and measurement principle are deliberately separate.
Portable devices are not silently copied into Form 11, and a mixed
"fixed+portable" row must be split by the company before statutory output.
"""

from dataclasses import dataclass
from collections.abc import Mapping
import re
from typing import Any

from .project import CONFIRMED_STATUSES, Stage2Project
from .cap_shared_facts import workspace_facility_rows


FIXED = {"고정식", "fixed"}
PORTABLE = {"휴대식", "portable"}
MIXED = {"고정식휴대식", "fixedportable", "portablefixed"}
YES = {"예", "yes", "y", "true", "1"}
NO = {"아니오", "아니요", "no", "n", "false", "0", "해당없음", "해당 없음", "n/a", "na"}
GENERIC_TARGETS = {
    "voc", "복합가스", "가연성가스", "독성가스", "산소", "o2",
    "lel", "가스", "유기가스", "유기용제증기",
}


@dataclass(frozen=True)
class CAPForm11Data:
    rows: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]
    excluded_portable_count: int = 0

    @property
    def ready(self) -> bool:
        return bool(self.rows) and not self.blockers


def _clean(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", _clean(value)).lower()


def _row_value(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_norm(k): v for k, v in row.items()}
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


def _installation_type(row: Mapping[str, Any]) -> str:
    explicit = _clean(_row_value(row, "설치형태", "설치 형식"))
    if explicit:
        return explicit

    legacy = _clean(_row_value(row, "감지방식"))
    # Legacy Stage 2 used 감지방식 for fixed/portable. Only consume it as
    # installation type when it actually contains an installation label.
    if _norm(legacy) in FIXED | PORTABLE | MIXED:
        return legacy
    return ""


def _measurement_method(row: Mapping[str, Any]) -> str:
    explicit = _clean(_row_value(row, "측정방식", "측정원리", "센서방식"))
    if explicit:
        return explicit

    legacy = _clean(_row_value(row, "감지방식"))
    if legacy and _norm(legacy) not in FIXED | PORTABLE | MIXED:
        return legacy
    return ""


def _yes_no(value: object) -> bool | None:
    text = _clean(value).lower()
    if text in YES:
        return True
    if text in NO:
        return False
    return None


def _chemical_names(project: Stage2Project) -> set[str]:
    rows = _confirmed_rows(project, "inventory.chemicals", "cap.chemical.details")
    names: set[str] = set()
    for row in rows:
        value = _row_value(row, "물질명", "유해화학물질명", "제품명")
        if _clean(value):
            names.add(_norm(value))
    return names


def _facility_tags(project: Stage2Project) -> set[str]:
    rows = workspace_facility_rows(project) or _confirmed_rows(
        project, "inventory.facilities", "cap.facility.equipment_specs"
    )
    return {
        _clean(_row_value(row, "설비번호", "구분기호", "장치번호")).upper()
        for row in rows
        if _clean(_row_value(row, "설비번호", "구분기호", "장치번호"))
    }


def _alarm_setting_specific(value: object) -> bool:
    text = _clean(value)
    if not text or not re.search(r"\d", text):
        return False
    lower = text.lower().replace(" ", "")
    unit_markers = ("ppm", "ppb", "%lel", "lel", "%", "mg/m3", "mg/m³", "vol%", "v/v")
    return any(marker in lower for marker in unit_markers)


def _operation_time_specific(value: object) -> bool:
    text = _clean(value)
    if not text or not re.search(r"\d", text):
        return False
    lower = text.lower().replace(" ", "")
    return any(marker in lower for marker in ("초", "sec", "second", "분", "min", "minute"))


def _location_tags(value: object) -> set[str]:
    text = _clean(value).upper()
    # Use only explicit Tag-like tokens. Ordinary place names are not inferred.
    return set(re.findall(r"\b[A-Z]{1,5}-\d{1,6}[A-Z]?\b", text))


def build_cap_form11_data(project: Stage2Project) -> CAPForm11Data:
    source_rows = _confirmed_rows(project, "cap.safety.gas_detection", "psm.psi.gas_detection")
    if not source_rows:
        return CAPForm11Data(
            (),
            ("고정식 유해감지시설 명세가 확인되지 않았습니다.",),
            (),
            0,
        )

    known_chemicals = _chemical_names(project)
    known_tags = _facility_tags(project)
    blockers: list[str] = []
    messages: list[str] = []
    out: list[dict[str, Any]] = []
    excluded_portable = 0

    for src_index, row in enumerate(source_rows, start=1):
        detector_id = _clean(_row_value(row, "감지기 번호", "감지기번호", "구분기호"))
        label = detector_id or f"{src_index}행"
        install = _installation_type(row)
        install_norm = _norm(install)

        if not install:
            blockers.append(
                f"{label}: 설치형태(고정식/휴대식)가 없어 별지 제11호 대상 여부를 판단할 수 없습니다."
            )
            continue
        if install_norm in PORTABLE:
            excluded_portable += 1
            continue
        if install_norm in MIXED:
            blockers.append(
                f"{label}: '고정식+휴대식'을 한 행에 함께 입력했습니다. "
                "별지 제11호는 고정식 설비만 작성하므로 각각 별도 행으로 분리해 주세요."
            )
            continue
        if install_norm not in FIXED:
            blockers.append(
                f"{label}: 설치형태 '{install}'를 고정식/휴대식으로 판정할 수 없습니다."
            )
            continue

        target = _clean(_row_value(row, "검출대상 물질", "감지대상", "검출대상"))
        location = _clean(_row_value(row, "설치위치", "설치장소"))
        operation_time = _clean(_row_value(row, "작동시간", "응답시간"))
        measurement = _measurement_method(row)
        alarm_setting = _clean(_row_value(row, "경보 설정값", "경보설정값"))
        alarm_location = _clean(_row_value(row, "경보 위치", "경보기 설치장소"))
        interlock_raw = _clean(_row_value(row, "연동여부", "인터록 연동여부"))
        interlock = _yes_no(interlock_raw)
        action = _clean(_row_value(row, "연동 설비·조치", "연동설비", "경보시 조치내용"))
        accuracy = _clean(_row_value(row, "정밀도", "정확도"))
        maintenance = _clean(_row_value(row, "유지관리", "점검주기", "교정주기"))
        emergency_power = _clean(_row_value(row, "비상전원 여부"))
        drawing = _clean(_row_value(row, "관련 도면번호", "도면번호"))
        note = _clean(_row_value(row, "비고"))

        if not detector_id:
            blockers.append(f"{label}: 감지기 번호(Tag)가 비어 있습니다.")
        if not target:
            blockers.append(f"{label}: 감지대상 물질이 비어 있습니다.")
        elif _norm(target) not in GENERIC_TARGETS and known_chemicals and _norm(target) not in known_chemicals:
            blockers.append(
                f"{label}: 감지대상 '{target}'을 회사 화학물질 목록의 물질명과 직접 연결하지 못했습니다. "
                "일반 감지범주라면 VOC·복합가스 등으로 명확히 입력해 주세요."
            )
        if not location:
            blockers.append(f"{label}: 설치위치가 비어 있습니다.")
        else:
            unknown_tags = sorted(tag for tag in _location_tags(location) if tag not in known_tags)
            if unknown_tags:
                blockers.append(
                    f"{label}: 설치위치에 적힌 설비 Tag {', '.join(unknown_tags)}가 03_설비정보에 없습니다."
                )

        if not _operation_time_specific(operation_time):
            blockers.append(
                f"{label}: 작동시간은 '30초 이내'처럼 수치와 시간단위를 포함한 제조사/사양서 값을 입력해 주세요."
            )
        if not measurement:
            blockers.append(
                f"{label}: 측정방식이 비어 있습니다. 고정식/휴대식은 측정방식이 아니라 설치형태입니다."
            )
        if not _alarm_setting_specific(alarm_setting):
            blockers.append(
                f"{label}: 경보설정값은 '0.5 ppm', '10% LEL'처럼 수치와 단위를 포함해 주세요."
            )
        if not alarm_location:
            blockers.append(f"{label}: 경보기 설치장소가 비어 있습니다.")
        if interlock is None:
            blockers.append(f"{label}: 연동여부를 예/아니오로 명확히 확인해 주세요.")
        elif interlock and not action:
            blockers.append(
                f"{label}: 연동여부가 '예'이지만 연동 설비·조치내용이 비어 있습니다."
            )
        if not accuracy:
            blockers.append(f"{label}: 정밀도/정확도 사양이 비어 있습니다.")
        if not maintenance:
            blockers.append(f"{label}: 유지관리 또는 점검·교정주기가 비어 있습니다.")

        remarks = []
        if action:
            remarks.append(f"연동조치: {action}")
        if emergency_power:
            remarks.append(f"비상전원: {emergency_power}")
        if drawing:
            remarks.append(f"도면: {drawing}")
        if note:
            remarks.append(note)

        out.append({
            "연번": len(out) + 1,
            "구분기호": detector_id,
            "감지대상": target,
            "설치위치": location,
            "작동시간": operation_time,
            "측정방식": measurement,
            "경보설정값": alarm_setting,
            "경보기 설치장소": alarm_location,
            "연동여부": "예" if interlock is True else ("아니오" if interlock is False else ""),
            "정밀도": accuracy,
            "유지관리": maintenance,
            "비고": " / ".join(remarks),
        })

    if not out:
        blockers.append(
            "CAP 별지 제11호에 작성할 고정식 유해감지시설이 확인되지 않았습니다. "
            "휴대식만 보유한 경우에도 법적 고정식 설치대상 여부를 확인하기 전에는 '해당 없음'으로 자동처리하지 않습니다."
        )

    if excluded_portable:
        messages.append(
            f"휴대식 감지기 {excluded_portable}건은 회사자료에는 유지하되 CAP 별지 제11호 고정식 명세에서 제외했습니다."
        )
    messages.append(
        "설치형태(고정식/휴대식)와 측정방식(전기화학식·접촉연소식·적외선식 등)을 별도 정보로 관리합니다."
    )
    messages.append(
        "경보설정값·작동시간·정밀도·유지관리 값은 제조사 사양서 또는 회사 승인 기준에서 확인하고 AI가 임의 생성하지 않습니다."
    )

    return CAPForm11Data(
        rows=tuple(out),
        blockers=tuple(dict.fromkeys(blockers)),
        messages=tuple(dict.fromkeys(messages)),
        excluded_portable_count=excluded_portable,
    )
