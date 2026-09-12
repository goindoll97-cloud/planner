from __future__ import annotations

from dataclasses import dataclass

from .project import Stage2Project


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


CAP_REQUIREMENTS: tuple[RequirementSpec, ...] = (
    RequirementSpec(
        key="cap.basic_info",
        system="CAP",
        section="기본정보",
        label="기본정보",
        description="사업장과 취급 유해화학물질 등 계획서 기본정보",
        field_keys=("business.company_name", "business.address", "inventory.chemicals"),
        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 제3조",
    ),
    RequirementSpec(
        key="cap.facility_info",
        system="CAP",
        section="시설정보",
        label="시설정보",
        description="유해화학물질 취급시설과 공정·저장시설의 정보 및 배치근거",
        field_keys=("inventory.facilities", "documents.site_plan"),
        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 제3조",
    ),
    RequirementSpec(
        key="cap.offsite_assessment",
        system="CAP",
        section="장외평가정보",
        label="장외평가정보",
        description="사고시나리오, 영향범위 및 주변지역 관련 장외평가 작성자료",
        field_keys=("cap.offsite_assessment",),
        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 제3조",
    ),
    RequirementSpec(
        key="cap.prevention_policy",
        system="CAP",
        section="사전관리방침",
        label="사전관리방침",
        description="사고예방을 위한 조직·운영·관리 방침과 이행자료",
        field_keys=("cap.prevention_policy",),
        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 제3조",
    ),
    RequirementSpec(
        key="cap.internal_emergency",
        system="CAP",
        section="내부 비상대응 계획",
        label="내부 비상대응 계획",
        description="사업장 내부의 사고 대응조직, 절차, 장비, 대피·교육·훈련 자료",
        field_keys=("emergency.internal_plan",),
        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 제3조",
    ),
    RequirementSpec(
        key="cap.external_emergency",
        system="CAP",
        section="외부 비상대응 계획",
        label="외부 비상대응 계획",
        description="사업장 외부 영향에 대한 연락·고지·대응 및 관계기관 연계 자료",
        field_keys=("emergency.external_plan",),
        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 제3조",
    ),
)


def requirement_specs_for_project(project: Stage2Project) -> list[RequirementSpec]:
    specs: list[RequirementSpec] = list(COMMON_REQUIREMENTS)
    if project.psm_required is True:
        specs.extend(PSM_REQUIREMENTS)
    if project.cap_required is True:
        specs.extend(CAP_REQUIREMENTS)

    # Stage 1에서 2군으로 확정된 경우 외부 비상대응계획은 작성대상 registry에서 제외한다.
    if project.cap_required is True and project.cap_group == "2군":
        specs = [spec for spec in specs if spec.key != "cap.external_emergency"]
    return specs
