from __future__ import annotations

from . import statutory_report as statutory
from .cap_chemical_legal import build_cap_chemical_legal_data
from .cap_sds_engine import build_cap_form6_sds_data, build_cap_form7_data
from .cap_form1_engine import build_cap_form1_data
from .cap_form2_engine import build_cap_form2_readiness
from .cap_form3_5_engine import (
    build_cap_form3_readiness,
    build_cap_form4_readiness,
    build_cap_form5_readiness,
)
from .cap_form8_engine import build_cap_form8_data
from .cap_form9_engine import build_cap_form9_data
from .cap_form10_engine import build_cap_form10_data
from .cap_form11_engine import build_cap_form11_data
from .cap_impact_engine import build_cap_form12_data, build_cap_form13_data
from .cap_risk_engine import build_cap_form14_data, build_cap_form15_data
from .cap_form16_engine import build_cap_form16_data
from .cross_validation import CrossValidationReport, ValidationIssue, validate_stage2_project
from .project import Stage2Project
from .psm_core_form_engine import build_all_psm_core_form_readiness
from .psm_form12_consequence_engine import (
    build_psm_form12_readiness,
    build_psm_form19_2_readiness,
)
from .psm_later_form_engine import build_all_psm_later_form_readiness


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

    if project.psm_in_scope:
        checked_rules += 1
        prepared = build_psm_form12_readiness(project)
        if prepared.blockers:
            for index, blocker in enumerate(prepared.blockers, start=1):
                issues_list.append(
                    ValidationIssue(
                        code=f"PSM-FORM12-{index}",
                        status="HOLD",
                        system="PSM",
                        section="사업개요",
                        legal_item="별지 제12호서식 사업개요",
                        message=str(blocker),
                        field_keys=("psm.business.form12_details",),
                        legal_basis=(
                            "공정안전보고서의 제출·심사·확인 및 이행상태평가 등에 관한 규정 "
                            "별지 제12호서식"
                        ),
                    )
                )
        else:
            issues_list.append(
                ValidationIssue(
                    code="PSM-FORM12-READY",
                    status="PASS",
                    system="PSM",
                    section="사업개요",
                    legal_item="별지 제12호서식 사업개요",
                    message=prepared.messages[0],
                    field_keys=("psm.business.form12_details",),
                    legal_basis=(
                        "공정안전보고서의 제출·심사·확인 및 이행상태평가 등에 관한 규정 "
                        "별지 제12호서식"
                    ),
                )
            )

    if project.psm_in_scope:
        psm_fields = {
            "13": ("psm.psi.chemical_details", "inventory.chemicals"),
            "14": ("psm.psi.machinery_list",),
            "15": ("psm.psi.equipment_specs", "inventory.facilities"),
            "16": ("psm.psi.piping_gasket_specs",),
            "17": ("psm.psi.relief_device_specs",),
        }
        for prepared in build_all_psm_core_form_readiness(project):
            checked_rules += 1
            legal_item = f"별지 제{prepared.form_no}호서식 {prepared.form_name}"
            legal_basis = (
                "공정안전보고서의 제출·심사·확인 및 이행상태평가 등에 관한 규정 "
                f"별지 제{prepared.form_no}호서식"
            )
            if prepared.blockers:
                for index, blocker in enumerate(prepared.blockers, start=1):
                    issues_list.append(
                        ValidationIssue(
                            code=f"PSM-FORM{prepared.form_no}-{index}",
                            status="HOLD",
                            system="PSM",
                            section="공정안전자료",
                            legal_item=legal_item,
                            message=str(blocker),
                            field_keys=psm_fields[prepared.form_no],
                            legal_basis=legal_basis,
                        )
                    )
            else:
                issues_list.append(
                    ValidationIssue(
                        code=f"PSM-FORM{prepared.form_no}-READY",
                        status="PASS",
                        system="PSM",
                        section="공정안전자료",
                        legal_item=legal_item,
                        message=prepared.messages[0] if prepared.messages else "핵심 작성칸을 확인했습니다.",
                        field_keys=psm_fields[prepared.form_no],
                        legal_basis=legal_basis,
                    )
                )

    if project.psm_in_scope:
        later_fields = {
            "17-2": ("psm.psi.form_applicability", "psm.psi.interlock_conditions"),
            "17-3": ("psm.psi.form_applicability", "psm.psi.fire_protection_table"),
            "17-4": ("psm.psi.form_applicability", "psm.psi.fire_detection_table"),
            "17-5": ("psm.psi.form_applicability", "psm.psi.gas_detection_table"),
            "18": ("psm.psi.form_applicability", "psm.psi.fireproofing_table"),
            "19": ("psm.psi.form_applicability", "psm.psi.local_exhaust_table"),
            "20": ("psm.psi.form_applicability", "psm.psi.ex_equipment"),
            "21": ("psm.risk.team",),
        }
        for prepared in build_all_psm_later_form_readiness(project):
            checked_rules += 1
            spec = statutory.PSM_FORMS[prepared.form_no]
            legal_item = f"{spec.reference} {prepared.form_name}"
            legal_basis = (
                "공정안전보고서의 제출·심사·확인 및 이행상태평가 등에 관한 규정 "
                f"{spec.reference}"
            )
            if prepared.blockers:
                for index, blocker in enumerate(prepared.blockers, start=1):
                    issues_list.append(
                        ValidationIssue(
                            code=f"PSM-FORM{prepared.form_no}-{index}",
                            status="HOLD",
                            system="PSM",
                            section="공정안전자료" if prepared.form_no != "21" else "공정위험성평가",
                            legal_item=legal_item,
                            message=str(blocker),
                            field_keys=later_fields[prepared.form_no],
                            legal_basis=legal_basis,
                        )
                    )
            else:
                issues_list.append(
                    ValidationIssue(
                        code=f"PSM-FORM{prepared.form_no}-READY",
                        status="PASS",
                        system="PSM",
                        section="공정안전자료" if prepared.form_no != "21" else "공정위험성평가",
                        legal_item=legal_item,
                        message=prepared.messages[0] if prepared.messages else "적용여부와 핵심 작성칸을 확인했습니다.",
                        field_keys=later_fields[prepared.form_no],
                        legal_basis=legal_basis,
                    )
                )

    if project.psm_in_scope:
        checked_rules += 1
        prepared = build_psm_form19_2_readiness(project)
        if prepared.blockers:
            for index, blocker in enumerate(prepared.blockers, start=1):
                issues_list.append(
                    ValidationIssue(
                        code=f"PSM-FORM19-2-{index}",
                        status="HOLD",
                        system="PSM",
                        section="공정위험성평가",
                        legal_item="별지 제19호의2서식 시나리오 및 피해예측 결과",
                        message=str(blocker),
                        field_keys=(
                            "psm.psi.form_applicability",
                            "psm.risk.consequence_table",
                            "psm.risk.consequence",
                        ),
                        legal_basis=(
                            "공정안전보고서의 제출·심사·확인 및 이행상태평가 등에 관한 규정 "
                            "별지 제19호의2서식"
                        ),
                    )
                )
        else:
            issues_list.append(
                ValidationIssue(
                    code="PSM-FORM19-2-READY",
                    status="PASS",
                    system="PSM",
                    section="공정위험성평가",
                    legal_item="별지 제19호의2서식 시나리오 및 피해예측 결과",
                    message=prepared.messages[0],
                    field_keys=(
                        "psm.psi.form_applicability",
                        "psm.risk.consequence_table",
                        "psm.risk.consequence",
                    ),
                    legal_basis=(
                        "공정안전보고서의 제출·심사·확인 및 이행상태평가 등에 관한 규정 "
                        "별지 제19호의2서식"
                    ),
                )
            )

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
        form2 = build_cap_form2_readiness(project)
        form2_fields = (
            "cap.business.submission_type",
            "cap.business.submission_reason",
            "cap.prevention.change_log",
        )
        if form2.status == "NOT_APPLICABLE":
            issues_list.append(
                ValidationIssue(
                    code="CAP-FORM2-NOT-APPLICABLE",
                    status="NOT_APPLICABLE",
                    system="CAP",
                    section="기본정보",
                    legal_item="별지 제2호 변경내역 관리대장",
                    message=form2.messages[0] if form2.messages else "현재 제출유형에서는 별지 제2호를 필수 작성항목으로 적용하지 않습니다.",
                    field_keys=form2_fields,
                    legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제2호서식",
                )
            )
        elif form2.status in {"HOLD", "REVIEW_REQUIRED"}:
            issue_status = form2.status
            for index, blocker in enumerate(form2.blockers, start=1):
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM2-{index}",
                        status=issue_status,
                        system="CAP",
                        section="기본정보",
                        legal_item="별지 제2호 변경내역 관리대장",
                        message=str(blocker),
                        field_keys=form2_fields,
                        legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제2호서식",
                    )
                )
        else:
            issues_list.append(
                ValidationIssue(
                    code="CAP-FORM2-READY",
                    status="PASS",
                    system="CAP",
                    section="기본정보",
                    legal_item="별지 제2호 변경내역 관리대장",
                    message=form2.messages[0] if form2.messages else "변경내역 관리대장을 확인했습니다.",
                    field_keys=form2_fields,
                    legal_basis="화학사고예방관리계획서 작성 등에 관한 규정 별지 제2호서식",
                )
            )

        for prepared, section, legal_item, field_keys in (
            (
                build_cap_form3_readiness(project),
                "기본정보",
                "별지 제3호 사업장 일반정보",
                (
                    "cap.business.unit_plant_name",
                    "cap.business.registration_no",
                    "cap.business.representative",
                    "business.address",
                    "cap.business.industrial_complex",
                    "cap.business.contact",
                    "cap.business.submission_type",
                    "cap.business.submission_reason",
                    "cap.business.joint_emergency_plan",
                    "cap.business.other_system_review",
                    "cap.business.residents_in_overall_range",
                    "cap.business.recent_accident",
                    "cap.business.writer_name",
                    "cap.business.writer_info",
                    "cap.business.writer_contact",
                    "cap.business.writer_email",
                ),
            ),
            (
                build_cap_form4_readiness(project),
                "기본정보",
                "별지 제4호 총괄 취급시설 개요",
                (
                    "cap.basic.total_facility_overview",
                    "process.description",
                    "inventory.facilities",
                    "cap.basic.loading_transport",
                    "inventory.chemicals",
                ),
            ),
            (
                build_cap_form5_readiness(project),
                "기본정보",
                "별지 제5호 세부 취급시설 개요",
                (
                    "cap.basic.unit_facility_overview",
                    "process.description",
                    "inventory.facilities",
                    "cap.basic.loading_transport",
                    "inventory.chemicals",
                ),
            ),
        ):
            checked_rules += 1
            if prepared.blockers:
                for index, blocker in enumerate(prepared.blockers, start=1):
                    issues_list.append(
                        ValidationIssue(
                            code=f"CAP-FORM{prepared.form_no}-{index}",
                            status="HOLD",
                            system="CAP",
                            section=section,
                            legal_item=legal_item,
                            message=str(blocker),
                            field_keys=field_keys,
                            legal_basis=(
                                "화학사고예방관리계획서 작성 등에 관한 규정 "
                                f"별지 제{prepared.form_no}호서식"
                            ),
                        )
                    )
            else:
                issues_list.append(
                    ValidationIssue(
                        code=f"CAP-FORM{prepared.form_no}-READY",
                        status="PASS",
                        system="CAP",
                        section=section,
                        legal_item=legal_item,
                        message=prepared.messages[0] if prepared.messages else "작성자료를 확인했습니다.",
                        field_keys=field_keys,
                        legal_basis=(
                            "화학사고예방관리계획서 작성 등에 관한 규정 "
                            f"별지 제{prepared.form_no}호서식"
                        ),
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
