from __future__ import annotations

"""공정안전보고서에서 파일이 본체인 첨부 자료(도면·MSDS)를 한곳에서 받는다.

표로 적을 수 있는 정보는 화면에서 입력하고, 도면처럼 파일 자체가 자료인 것만 올린다. 올린 파일은 SHA-256과 함께 기록하고
서식의 해당 첨부 칸에 연결한다. 파일을 받았다고 내용을 확인한 것으로 보지 않으므로, 담당자가 '내용을 확인했다'고 표시하기 전까지는 HOLD다.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .project import EvidenceRef, Stage2Project
from . import storage


@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    help: str


SLOTS = (
    Slot("psm.psi.msds", "물질안전보건자료(MSDS)", "취급하는 유해·위험물질의 MSDS입니다. 물질별로 묶어 한 파일로 올려도 됩니다."),
    Slot("documents.pfd", "공정흐름도(PFD)", "공정의 흐름을 나타내는 도면입니다."),
    Slot("documents.pid", "공정배관·계장도(P&ID)", "배관과 계장을 나타내는 도면입니다. 장치번호와 같은 기호를 씁니다."),
    Slot("documents.site_plan", "공장 전체배치도", "사업장 전체의 건물·설비 배치를 나타내는 도면입니다."),
    Slot("psm.psi.equipment_layout", "설비배치도", "공정 설비의 배치를 나타내는 도면입니다."),
    Slot("psm.psi.building_structure", "건물·철구조물 평면도 및 입면도", "건물과 철구조물의 평면도·입면도입니다."),
    Slot("psm.psi.ufd", "유틸리티 계통도·배관계장도(UFD)", "질소·냉각수·증기 같은 유틸리티 계통도입니다."),
    Slot("psm.psi.single_line", "전기단선도", "전기 계통을 단순하게 나타낸 도면입니다."),
    Slot("psm.psi.short_circuit", "단락용량 계산서", "전기 단락용량을 계산한 자료입니다."),
    Slot("psm.psi.emergency_power", "비상전원 설비용량 자료", "비상 발전기 등 비상전원 설비의 용량 자료입니다."),
    Slot("psm.psi.grounding", "접지계획·배치도", "접지 계획과 접지 배치도입니다."),
    Slot("psm.psi.hazardous_area", "폭발위험장소 구분도", "폭발 위험이 있는 장소(0·1·2종)를 구분해 그린 도면입니다."),
    Slot("psm.psi.design_installation_guideline", "안전설계·제작 및 설치 관련 지침서", "회사가 쓰는 안전설계·제작·설치 지침서입니다."),
    Slot("psm.risk.report", "공정위험성평가 보고서", "회사가 수행한 위험성평가(HAZOP 등) 결과 보고서입니다. 사고예방·피해 최소화 대책 초안의 근거가 됩니다."),
    Slot("psm.risk.procedure", "위험성평가 절차서", "회사의 위험성평가 절차서입니다."),
    Slot("psm.operation.work_permit", "안전작업허가 절차·양식", "회사가 쓰는 안전작업허가 절차서와 양식입니다."),
    Slot("psm.operation.contractor", "도급업체 안전관리계획", "도급업체 안전관리 계획서입니다."),
    Slot("psm.operation.prestartup", "가동 전 점검지침", "가동 전 점검 지침과 점검표입니다."),
)
_BY_KEY = {slot.key: slot for slot in SLOTS}


def attach(project: Stage2Project, key: str, file_name: str, data: bytes, *, reference_no: str = "",
           revision: str = "", confirmed: bool = False, root: Path | None = None) -> EvidenceRef:
    if key not in _BY_KEY:
        raise ValueError(f"지원하지 않는 첨부 항목입니다: {key}")
    if not data:
        raise ValueError("빈 파일은 올릴 수 없습니다.")
    kwargs = {"root": root} if root else {}
    evidence = storage.save_attachment(project.project_id, file_name, data, note=_BY_KEY[key].label, **kwargs)
    project.set_field(
        key, _BY_KEY[key].label,
        {"file_name": evidence.source_name, "reference_no": reference_no.strip(), "revision": revision.strip(),
         "sha256": evidence.sha256},
        "USER_CONFIRMED" if confirmed else "HOLD", evidence=[evidence],
        note="담당자가 내용을 확인함" if confirmed else "파일만 접수됨. 내용 확인 전")
    return evidence


def confirm(project: Stage2Project, key: str) -> bool:
    record = project.get_field(key)
    if record is None or not isinstance(record.value, dict):
        return False
    project.set_field(key, record.label, record.value, "USER_CONFIRMED", evidence=list(record.evidence),
                      note="담당자가 내용을 확인함")
    return True


def status(project: Stage2Project) -> list[dict[str, Any]]:
    out = []
    for slot in SLOTS:
        record = project.get_field(slot.key)
        value = record.value if record is not None and isinstance(record.value, dict) else {}
        out.append({"slot": slot, "file_name": value.get("file_name", ""), "reference_no": value.get("reference_no", ""),
                    "revision": value.get("revision", ""), "sha256": value.get("sha256", ""),
                    "state": ("확인 완료" if record is not None and record.status == "USER_CONFIRMED" else
                              "내용 확인 필요" if value else "올리지 않음")})
    return out
