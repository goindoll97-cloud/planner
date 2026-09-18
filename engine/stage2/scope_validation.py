from __future__ import annotations

from .cap_chemical_legal import build_cap_chemical_legal_data
from .cap_form1_engine import build_cap_form1_data
from .cap_form9_engine import build_cap_form9_data
from .cap_form10_engine import build_cap_form10_data
from .cross_validation import CrossValidationReport, ValidationIssue, validate_stage2_project
from .project import Stage2Project


def validate_selected_scope(project: Stage2Project) -> CrossValidationReport:
    """Run existing validation and keep only issues in the selected authoring scope."""
    if not project.scope_confirmed:
        return CrossValidationReport(issues=(), checked_rules=0)

    raw = validate_stage2_project(project)
    allowed_systems = {"COMMON"}
    if project.psm_in_scope:
        allowed_systems.add("PSM")
    if project.cap_in_scope:
        allowed_systems.add("CAP")

    issues_list: list[ValidationIssue] = [
        issue for issue in raw.issues if issue.system in allowed_systems
    ]
    checked_rules = raw.checked_rules

    if project.cap_in_scope:
        checked_rules += 1
        form1 = build_cap_form1_data(project)
        if form1.blockers:
            for index, blocker in enumerate(form1.blockers, start=1):
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM1-{index}",
                        status="HOLD",
                        system="CAP",
                        section="기본정보",
                        legal_item="별지 제1호 사업장의 작성수준 구분",
                        message=str(blocker),
                        field_keys=("inventory.chemicals", "inventory.facilities"),
                        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제1호서식",
                    )
                )
        else:
            issues_list.append(
                ValidationIssue(
                    code="CAP-FORM1-READY",
                    status="PASS",
                    system="CAP",
                    section="기본정보",
                    legal_item="별지 제1호 사업장의 작성수준 구분",
                    message="물질구분, 규정수량 및 최대보유량 ton 정규화 결과를 확인했습니다.",
                    field_keys=("inventory.chemicals", "inventory.facilities"),
                    legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제1호서식",
                )
            )

        checked_rules += 1
        form6 = build_cap_chemical_legal_data(project)
        if form6.blockers:
            for index, blocker in enumerate(form6.blockers, start=1):
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM6-{index}",
                        status="HOLD",
                        system="CAP",
                        section="기본정보",
                        legal_item="별지 제6호 유해화학물질 목록 및 명세",
                        message=str(blocker),
                        field_keys=("inventory.chemicals", "cap.chemical.details"),
                        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제6호서식",
                    )
                )
        else:
            issues_list.append(
                ValidationIssue(
                    code="CAP-FORM6-READY",
                    status="PASS",
                    system="CAP",
                    section="기본정보",
                    legal_item="별지 제6호 유해화학물질 목록 및 명세",
                    message="현행 별표 2 고유번호와 별표 2·3 물질구분을 확인했습니다.",
                    field_keys=("inventory.chemicals", "cap.chemical.details"),
                    legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제6호서식",
                )
            )

        checked_rules += 1
        form9 = build_cap_form9_data(project)
        if form9.blockers:
            for index, blocker in enumerate(form9.blockers, start=1):
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM9-{index}",
                        status="HOLD",
                        system="CAP",
                        section="시설정보",
                        legal_item="별지 제9호 장치·설비 목록 및 명세",
                        message=str(blocker),
                        field_keys=("inventory.facilities", "cap.facility.equipment_specs"),
                        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제9호서식",
                    )
                )
        else:
            issues_list.append(
                ValidationIssue(
                    code="CAP-FORM9-READY",
                    status="PASS",
                    system="CAP",
                    section="시설정보",
                    legal_item="별지 제9호 장치·설비 목록 및 명세",
                    message="설비명세 필수값과 법정 단위 ton/m3/MPa 정규화를 확인했습니다.",
                    field_keys=("inventory.facilities", "cap.facility.equipment_specs"),
                    legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제9호서식",
                )
            )

        checked_rules += 1
        form10 = build_cap_form10_data(project)
        if form10.blockers:
            for index, blocker in enumerate(form10.blockers, start=1):
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM10-{index}",
                        status="HOLD",
                        system="CAP",
                        section="시설정보",
                        legal_item="별지 제10호 확산방지설비 현황",
                        message=str(blocker),
                        field_keys=("cap.safety.dike_calculation", "cap.safety.dike_layout"),
                        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제10호서식",
                    )
                )
        else:
            issues_list.append(
                ValidationIssue(
                    code="CAP-FORM10-READY",
                    status="PASS",
                    system="CAP",
                    section="시설정보",
                    legal_item="별지 제10호 확산방지설비 현황",
                    message="필요용량 근거, 유효용량 산정 및 적정성 검토결과를 확인했습니다.",
                    field_keys=("cap.safety.dike_calculation", "cap.safety.dike_layout"),
                    legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제10호서식",
                )
            )

    order = {"HOLD": 0, "REVIEW_REQUIRED": 1, "PASS": 2, "NOT_APPLICABLE": 3}
    issues_list.sort(key=lambda issue: (order.get(issue.status, 9), issue.system, issue.section, issue.code))
    return CrossValidationReport(issues=tuple(issues_list), checked_rules=checked_rules)
