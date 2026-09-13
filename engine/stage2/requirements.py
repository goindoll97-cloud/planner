from __future__ import annotations

from dataclasses import dataclass
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .project import Stage2Project


CAP_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "stage2" / "cap_manual_registry.json"


@dataclass(frozen=True)
class RequirementSpec:
    key: str
    system: str
    section: str
    label: str
    description: str
    field_keys: tuple[str, ...] = ()
    evidence_required: bool = True
    required: bool = True
    legal_basis: str = ""
    manual_pages: tuple[int, ...] = ()
    input_kind: str = ""
    source_owner: str = ""
    suggested_evidence: tuple[str, ...] = ()
    automation: str = ""
    request_text: str = ""


COMMON_REQUIREMENTS: tuple[RequirementSpec, ...] = (
    RequirementSpec(
        key="common.business",
        system="COMMON",
        section="공통 사업장정보",
        label="사업장 기본정보",
        description="회사명, 사업장명, 소재지 등 작성대상 사업장의 식별정보",
        field_keys=("business.company_name", "business.address"),
        legal_basis="Stage 1 회사 입력자료 승계",
    ),
    RequirementSpec(
        key="common.chemicals",
        system="COMMON",
        section="공통 물질정보",
        label="화학물질 목록",
        description="작성대상 공정·시설에서 취급하는 화학물질과 물질 식별정보",
        field_keys=("inventory.chemicals",),
        legal_basis="Stage 1 회사 입력자료 승계",
    ),
    RequirementSpec(
        key="common.facilities",
        system="COMMON",
        section="공통 시설정보",
        label="시설·설비 목록",
        description="저장·취급시설 및 주요 공정설비의 식별과 기본 제원",
        field_keys=("inventory.facilities",),
        legal_basis="Stage 1 회사 입력자료 및 Stage 2 설비자료",
    ),
    RequirementSpec(
        key="common.process_description",
        system="COMMON",
        section="공통 공정정보",
        label="공정 설명",
        description="공정 흐름, 주요 운전단계, 투입·생성물 및 정상 운전조건을 설명하는 확인자료",
        field_keys=("process.description",),
    ),
    RequirementSpec(
        key="common.pfd",
        system="COMMON",
        section="공통 도면",
        label="공정흐름도(PFD)",
        description="작성대상 공정의 공정흐름을 확인할 수 있는 도면",
        field_keys=("documents.pfd",),
    ),
    RequirementSpec(
        key="common.pid",
        system="COMMON",
        section="공통 도면",
        label="배관계장도(P&ID)",
        description="배관, 계기, 차단·안전설비 등 공정 상세를 확인할 수 있는 도면",
        field_keys=("documents.pid",),
    ),
    RequirementSpec(
        key="common.site_plan",
        system="COMMON",
        section="공통 도면",
        label="사업장·설비 배치도",
        description="사업장 경계, 공정·저장시설 및 주요 안전·비상시설의 위치를 확인할 수 있는 도면",
        field_keys=("documents.site_plan",),
    ),
)


PSM_REQUIREMENTS: tuple[RequirementSpec, ...] = (
    RequirementSpec(
        key="psm.process_safety_information",
        system="PSM",
        section="공정안전자료",
        label="공정안전자료",
        description="유해·위험물질, 공정기술, 설비·도면 등 공정안전자료의 작성근거가 확인되어야 함",
        field_keys=("inventory.chemicals", "inventory.facilities", "process.description", "documents.pfd", "documents.pid"),
        legal_basis="산업안전보건법상 공정안전보고서 작성·심사 체계",
    ),
    RequirementSpec(
        key="psm.hazard_assessment",
        system="PSM",
        section="공정위험성평가",
        label="공정위험성평가",
        description="적용한 위험성평가 기법, 평가범위, 위험요인 및 개선조치가 확인되어야 함",
        field_keys=("psm.hazard_assessment",),
        legal_basis="공정안전보고서 심사기준의 위험성평가 분야",
    ),
    RequirementSpec(
        key="psm.safe_operation_plan",
        system="PSM",
        section="안전운전계획",
        label="안전운전계획",
        description="안전운전절차와 설비 유지관리, 작업허가, 변경관리 등 운영계획의 근거자료",
        field_keys=("psm.safe_operation_plan",),
        legal_basis="공정안전보고서 심사기준의 안전운전계획 분야",
    ),
    RequirementSpec(
        key="psm.emergency_plan",
        system="PSM",
        section="비상조치계획",
        label="비상조치계획",
        description="비상대응 조직, 대피, 공정 안전조치, 교육·훈련 및 사고시나리오 대응계획",
        field_keys=("emergency.internal_plan",),
        legal_basis="공정안전보고서 심사기준의 비상조치계획 분야",
    ),
)


@lru_cache(maxsize=1)
def load_cap_manual_registry() -> dict[str, Any]:
    with CAP_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("schema_version") != "cap-manual-registry-v1":
        raise ValueError("지원하지 않는 화학사고예방관리계획서 매뉴얼 registry 버전입니다.")
    return raw


def cap_field_labels() -> dict[str, str]:
    return dict(load_cap_manual_registry().get("field_labels") or {})


def cap_manual_source() -> dict[str, Any]:
    return dict(load_cap_manual_registry().get("source") or {})


def _cap_requirement_from_row(row: dict[str, Any]) -> RequirementSpec:
    pages = tuple(int(v) for v in row.get("manual_pages") or [])
    basis = str(row.get("manual_basis") or "").strip()
    description = str(row.get("request") or row.get("label") or "").strip()
    return RequirementSpec(
        key=str(row["key"]),
        system="CAP",
        section=str(row.get("section") or ""),
        label=str(row.get("label") or row["key"]),
        description=description,
        field_keys=tuple(str(v) for v in row.get("field_keys") or []),
        evidence_required=True,
        required=True,
        legal_basis=basis,
        manual_pages=pages,
        input_kind=str(row.get("input_kind") or ""),
        source_owner=str(row.get("source_owner") or ""),
        suggested_evidence=tuple(str(v) for v in row.get("suggested_evidence") or []),
        automation=str(row.get("automation") or ""),
        request_text=str(row.get("request") or ""),
    )


def cap_requirement_specs(group: str) -> list[RequirementSpec]:
    registry = load_cap_manual_registry()
    selected: list[RequirementSpec] = []
    for row in registry.get("requirements") or []:
        applies_to = {str(v) for v in row.get("applies_to") or []}
        if group and group not in applies_to:
            continue
        selected.append(_cap_requirement_from_row(row))
    return selected


def requirement_specs_for_project(project: Stage2Project) -> list[RequirementSpec]:
    specs: list[RequirementSpec] = list(COMMON_REQUIREMENTS)
    if project.psm_required is True:
        specs.extend(PSM_REQUIREMENTS)
    if project.cap_required is True:
        # Stage 1에서 작성수준이 확정되지 않았다면 fail closed: 1군 항목까지 포함한다.
        group = project.cap_group if project.cap_group in {"1군", "2군"} else "1군"
        specs.extend(cap_requirement_specs(group))
    return specs
