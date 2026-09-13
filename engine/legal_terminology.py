from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


TERMINOLOGY_PATH = Path(__file__).resolve().parents[1] / "data" / "legal_terminology.json"

# Requirement/field-specific canonical terms. These values follow the current
# statute/subordinate rule wording rather than legacy example-book wording.
PSM_SECTION_BY_PREFIX = {
    "psm.psi.": "공정안전자료",
    "psm.risk.": "공정위험성평가서",
    "psm.operation.": "안전운전계획",
    "psm.emergency.": "비상조치계획",
}

PSM_FIELD_LABEL_OVERRIDES = {
    "inventory.chemicals": "취급·저장하고 있거나 취급·저장하려는 유해·위험물질의 종류 및 수량",
    "psm.psi.msds": "유해·위험물질에 대한 물질안전보건자료",
    "inventory.facilities": "유해하거나 위험한 설비의 목록 및 사양",
    "psm.risk.report": "공정위험성평가서",
    "psm.operation.maintenance": "설비점검·검사 및 보수계획, 유지계획 및 지침서",
    "psm.operation.work_permit": "안전작업허가",
    "psm.operation.contractor": "도급업체 안전관리계획",
    "psm.operation.training": "근로자 등 교육계획",
    "psm.operation.prestartup": "가동 전 점검지침",
    "psm.operation.moc": "변경요소 관리계획",
    "psm.operation.other": "그 밖에 안전운전에 필요한 사항",
    "psm.emergency.resources": "비상조치를 위한 장비·인력 보유현황",
    "psm.emergency.contacts": "사고발생 시 각 부서·관련 기관과의 비상연락체계",
    "psm.emergency.roles_procedures": "사고발생 시 비상조치를 위한 조직의 임무 및 수행 절차",
    "psm.emergency.training": "비상조치계획에 따른 교육계획",
    "psm.emergency.public_information": "주민홍보계획",
    "psm.emergency.other": "그 밖에 비상조치 관련 사항",
}

CAP_CANONICAL_SECTIONS = {
    "기본정보",
    "시설정보",
    "장외평가정보",
    "사전관리방침",
    "내부 비상대응계획",
    "외부 비상대응계획",
}


@lru_cache(maxsize=1)
def load_legal_terminology() -> dict[str, Any]:
    with TERMINOLOGY_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("schema_version") != "legal-terminology-v1":
        raise ValueError("지원하지 않는 법령 용어사전 버전입니다.")
    return raw


def psm_section_name(requirement_key: str, fallback: str = "") -> str:
    for prefix, section in PSM_SECTION_BY_PREFIX.items():
        if requirement_key.startswith(prefix):
            return section
    return fallback


def psm_field_label(field_key: str, fallback: str = "") -> str:
    return PSM_FIELD_LABEL_OVERRIDES.get(field_key, fallback or field_key)


def is_current_cap_section(section: str) -> bool:
    return section in CAP_CANONICAL_SECTIONS
