from __future__ import annotations

"""화학사고예방관리계획서 최종 제출 확인: 타 제도 심사결과 활용과 공동제출 여부, 그리고 그에 딸린 증빙 파일.

최종 체크포인트(cap_final_gate)는 두 사실이 확인되어야 하고, '해당'·'공동제출'이면 실제 회사 증빙 파일이 연결되어야 통과시킨다.
파일을 올렸다는 이유만으로 사실을 새로 확정하지 않는다: 먼저 사실(예/아니오)을 확정한 뒤에만 증빙을 연결한다.
"""

from typing import Any

from .field_evidence import attach_evidence_to_confirmed_field
from .project import EvidenceRef, Stage2Project
from . import storage

OTHER_KEY = "cap.business.other_system_review"
JOINT_KEY = "cap.business.joint_emergency_plan"
OTHER_OPTIONS = ("미해당", "해당")
JOINT_OPTIONS = ("단독제출", "공동제출")
LABELS = {OTHER_KEY: "타 제도 심사결과 활용 여부", JOINT_KEY: "공동비상대응계획 해당 여부"}
NOTES = {OTHER_KEY: "타 제도 심사결과 활용 최종 제출 증빙", JOINT_KEY: "공동비상대응계획 최종 제출 증빙"}


def _record(project: Stage2Project, key: str):
    return project.get_field(key)


def answer(project: Stage2Project, key: str) -> str:
    record = _record(project, key)
    return "" if record is None or record.value is None else str(record.value).strip()


def needs_evidence(project: Stage2Project, key: str) -> bool:
    value = answer(project, key)
    return value.startswith("해당") if key == OTHER_KEY else "공동" in value


def evidence_names(project: Stage2Project, key: str) -> list[str]:
    record = _record(project, key)
    return [ref.source_name for ref in (record.evidence if record else []) if ref.source_name]


def save_answers(project: Stage2Project, other: str, joint: str) -> None:
    """사실을 확정한다. 값이 같으면 이미 연결한 증빙을 유지하고, 증빙이 필요 없는 값으로 바뀌면 증빙 연결을 없앤다."""
    for key, value in ((OTHER_KEY, other), (JOINT_KEY, joint)):
        if not value:
            continue
        previous = _record(project, key)
        keep = previous is not None and str(previous.value).strip() == value
        evidence = list(previous.evidence) if keep and previous is not None else []
        project.set_field(key, LABELS[key], value, "USER_CONFIRMED", evidence=evidence)


def link_evidence(project: Stage2Project, key: str, file_name: str, data: bytes) -> bool:
    """확정된 사실에 증빙 파일을 연결한다. 이미 같은 파일이면 False."""
    if key not in LABELS:
        raise ValueError(f"지원하지 않는 항목입니다: {key}")
    if not needs_evidence(project, key):
        raise ValueError("증빙이 필요한 값('해당' 또는 '공동제출')으로 확정한 뒤에 파일을 연결할 수 있습니다.")
    if not data:
        raise ValueError("빈 파일은 올릴 수 없습니다.")
    reference: EvidenceRef = storage.save_attachment(project.project_id, file_name, data, source_type="COMPANY_EVIDENCE",
                                                     note=NOTES[key])
    return attach_evidence_to_confirmed_field(project, key, reference, note="회사가 증빙 파일을 직접 연결")
