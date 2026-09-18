from __future__ import annotations

from .cap_chemical_legal import build_cap_chemical_legal_data
from .cap_sds_engine import build_cap_form6_sds_data, build_cap_form7_data
from .cap_form1_engine import build_cap_form1_data
from .cap_form8_engine import build_cap_form8_data
from .cap_form9_engine import build_cap_form9_data
from .cap_form10_engine import build_cap_form10_data
from .cap_form11_engine import build_cap_form11_data
from .cap_impact_engine import build_cap_form12_data, build_cap_form13_data
from .cap_risk_engine import build_cap_form14_data, build_cap_form15_data
from .cap_form16_engine import build_cap_form16_data
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
        form6 = build_cap_form6_sds_data(project)
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
                    message="현행 법적 물질정보와 회사 제품 SDS의 물성값·파일명·개정일을 확인했습니다.",
                    field_keys=("inventory.chemicals", "cap.chemical.details"),
                    legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제6호서식",
                )
            )

        checked_rules += 1
        form7 = build_cap_form7_data(project)
        if form7.blockers:
            for index, blocker in enumerate(form7.blockers, start=1):
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM7-{index}",
                        status="HOLD",
                        system="CAP",
                        section="기본정보",
                        legal_item="별지 제7호 유해화학물질의 유해성 정보",
                        message=str(blocker),
                        field_keys=("cap.chemical.hazard_information", "cap.chemical.details"),
                        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제7호서식",
                    )
                )
        else:
            issues_list.append(
                ValidationIssue(
                    code="CAP-FORM7-READY",
                    status="PASS",
                    system="CAP",
                    section="기본정보",
                    legal_item="별지 제7호 유해화학물질의 유해성 정보",
                    message="회사 SDS의 인체·물리·환경 유해성, 출처·선정사유와 별지 제1·6호 연계값을 확인했습니다.",
                    field_keys=("cap.chemical.hazard_information", "cap.chemical.details"),
                    legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제7호서식",
                )
            )

        checked_rules += 1
        form8 = build_cap_form8_data(project)
        if form8.blockers:
            for index, blocker in enumerate(form8.blockers, start=1):
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM8-{index}",
                        status="HOLD",
                        system="CAP",
                        section="기본정보",
                        legal_item="별지 제8호 사업장 주변 환경 정보",
                        message=str(blocker),
                        field_keys=("cap.site.surrounding_environment", "documents.site_plan"),
                        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제8호서식",
                    )
                )
        else:
            issues_list.append(
                ValidationIssue(
                    code="CAP-FORM8-READY",
                    status="PASS",
                    system="CAP",
                    section="기본정보",
                    legal_item="별지 제8호 사업장 주변 환경 정보",
                    message="500m 내 보호대상 명세 또는 보호대상 없음 확인과 GIS/현장 근거를 확인했습니다.",
                    field_keys=("cap.site.surrounding_environment",),
                    legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제8호서식",
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

        checked_rules += 1
        form11 = build_cap_form11_data(project)
        if form11.blockers:
            for index, blocker in enumerate(form11.blockers, start=1):
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM11-{index}",
                        status="HOLD",
                        system="CAP",
                        section="시설정보",
                        legal_item="별지 제11호 고정식 유해감지시설 명세",
                        message=str(blocker),
                        field_keys=("cap.safety.gas_detection", "psm.psi.gas_detection"),
                        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제11호서식",
                    )
                )
        else:
            issues_list.append(
                ValidationIssue(
                    code="CAP-FORM11-READY",
                    status="PASS",
                    system="CAP",
                    section="시설정보",
                    legal_item="별지 제11호 고정식 유해감지시설 명세",
                    message="고정식 감지기 대상선별과 작동시간·측정방식·경보·연동·정밀도·유지관리 값을 확인했습니다.",
                    field_keys=("cap.safety.gas_detection", "psm.psi.gas_detection"),
                    legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제11호서식",
                )
            )

        checked_rules += 2
        form12 = build_cap_form12_data(project)
        form13 = build_cap_form13_data(project)
        for form_no, prepared, field_keys, legal_item in (
            (
                12, form12,
                ("cap.offsite.scenario_impact_table",),
                "별지 제12호 사고시나리오 사업장 주변지역 영향 평가",
            ),
            (
                13, form13,
                ("cap.offsite.overall_impact_summary", "cap.offsite.population_and_protected_targets", "documents.kora_impact_result"),
                "별지 제13호 총괄영향범위 사업장 주변지역 영향 평가",
            ),
        ):
            if prepared.blockers:
                for index, blocker in enumerate(prepared.blockers, start=1):
                    issues_list.append(
                        ValidationIssue(
                            code=f"CAP-FORM{form_no}-{index}",
                            status="HOLD",
                            system="CAP",
                            section="장외평가정보",
                            legal_item=legal_item,
                            message=str(blocker),
                            field_keys=field_keys,
                            legal_basis=f"화학사고예방관리계획서 작성 등에 관한 규정 별지 제{form_no}호서식",
                        )
                    )
            else:
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM{form_no}-READY",
                        status="PASS",
                        system="CAP",
                        section="장외평가정보",
                        legal_item=legal_item,
                        message=(
                            "시나리오별 KORA/GIS 영향평가 값과 회사 물질·설비자료의 정합성을 확인했습니다."
                            if form_no == 12
                            else "총괄영향범위 GIS/KORA 확정요약, 보호대상 명세 및 결과파일을 확인했습니다."
                        ),
                        field_keys=field_keys,
                        legal_basis=f"화학사고예방관리계획서 작성 등에 관한 규정 별지 제{form_no}호서식",
                    )
                )

        checked_rules += 2
        form14 = build_cap_form14_data(project)
        form15 = build_cap_form15_data(project)
        if form15.no_offsite_scenario:
            form14 = type(form14)(
                scenario_rows=(),
                event_rows=(),
                blockers=(),
                messages=("장외 사고시나리오 없음 확정으로 별지 제14호 시설빈도 작성대상 없음",),
            )
        for form_no, prepared, field_keys, legal_item in (
            (
                14, form14,
                ("cap.offsite.scenario_frequency",),
                "별지 제14호 사고시나리오별 시설빈도",
            ),
            (
                15, form15,
                ("cap.offsite.scenario_impact_table", "cap.offsite.scenario_frequency"),
                "별지 제15호 위험도 분석",
            ),
        ):
            if prepared.blockers:
                for index, blocker in enumerate(prepared.blockers, start=1):
                    issues_list.append(
                        ValidationIssue(
                            code=f"CAP-FORM{form_no}-{index}",
                            status="HOLD",
                            system="CAP",
                            section="장외평가정보",
                            legal_item=legal_item,
                            message=str(blocker),
                            field_keys=field_keys,
                            legal_basis=f"화학사고예방관리계획서 작성 등에 관한 규정 별지 제{form_no}호서식",
                        )
                    )
            else:
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM{form_no}-READY",
                        status="PASS",
                        system="CAP",
                        section="장외평가정보",
                        legal_item=legal_item,
                        message=(
                            "개시사건 빈도×개수와 시나리오 시설빈도를 확인했습니다."
                            if form_no == 14
                            else "A·B·C·D 합계와 별표 3 구간점수를 확인했습니다."
                        ),
                        field_keys=field_keys,
                        legal_basis=f"화학사고예방관리계획서 작성 등에 관한 규정 별지 제{form_no}호서식",
                    )
                )

        checked_rules += 1
        form16 = build_cap_form16_data(project)
        if form16.blockers:
            for index, blocker in enumerate(form16.blockers, start=1):
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM16-{index}",
                        status="HOLD",
                        system="CAP",
                        section="비상대응분야 요약서",
                        legal_item="별지 제16호 화학사고예방관리계획서 비상대응분야 요약서",
                        message=str(blocker),
                        field_keys=(
                            "cap.business.writer_name",
                            "cap.business.writer_contact",
                            "cap.business.writer_email",
                            "cap.offsite.scenario_impact_table",
                            "cap.offsite.scenario_frequency",
                            "cap.prevention.emergency_contact_system",
                            "cap.internal.shutdown_authority",
                            "cap.internal.shutdown_procedure",
                            "cap.internal.communication_system",
                        ),
                        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제16호서식",
                    )
                )
        else:
            issues_list.append(
                ValidationIssue(
                    code="CAP-FORM16-READY",
                    status="PASS",
                    system="CAP",
                    section="비상대응분야 요약서",
                    legal_item="별지 제16호 화학사고예방관리계획서 비상대응분야 요약서",
                    message="사업장 일반정보, 작성일, 사고시나리오 물질·사고유형, 위험도 핵심정보 및 비상대응 요약을 확인했습니다.",
                    field_keys=(
                        "cap.offsite.scenario_impact_table",
                        "cap.offsite.scenario_frequency",
                        "cap.prevention.emergency_contact_system",
                    ),
                    legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제16호서식",
                )
            )

    order = {"HOLD": 0, "REVIEW_REQUIRED": 1, "PASS": 2, "NOT_APPLICABLE": 3}
    issues_list.sort(key=lambda issue: (order.get(issue.status, 9), issue.system, issue.section, issue.code))
    return CrossValidationReport(issues=tuple(issues_list), checked_rules=checked_rules)
