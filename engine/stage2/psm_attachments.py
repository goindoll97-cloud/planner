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
