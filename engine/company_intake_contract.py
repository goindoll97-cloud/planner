from __future__ import annotations

"""Company-fact intake contract shared by Stage 1 and final-report authoring.

The first company workbook should ask the company only for facts that cannot be
safely invented by AI or derived by the rule engine. Narrative drafting,
regulatory calculations, applicability decisions, writing level, and other
interpretive fields remain outside the company-direct input contract.

``COMPANY_FACT_SPECS`` drives the ``01_사업장기본정보`` sheet
(``engine.template._build_business_sheet``) and ``seed_company_facts`` carries
those confirmed facts into Stage 2 project fields
(``engine.stage2.project.create_project_from_stage1_snapshot``) so the PSM and
CAP statutory-form writers can reuse them without asking again.
"""

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence


UNKNOWN_TOKENS = {"", "모름", "잘모름", "미확인", "unknown"}

# Pre-release workbooks exposed developer abbreviations (PSM/CAP) as the
# company-facing labels below; user-facing text now always uses the full
# legal/report name, but a company_intake_workbook produced before that
# still has the old label as its column header, so seed_company_facts
# accepts either.
LABEL_ALIASES: tuple[tuple[str, str], ...] = (
    ("PSM 사업 구분", "공정안전보고서 사업 구분"),
    ("PSM 심사대상 설비명", "공정안전보고서 심사대상 설비명"),
    ("PSM 부지면적(㎡)", "공정안전보고서 부지면적(㎡)"),
    ("PSM 주요건물(동/층/연면적)", "공정안전보고서 주요건물(동/층/연면적)"),
    ("PSM 보고서 작성자 성명", "공정안전보고서 작성자 성명"),
    ("PSM 보고서 작성자 자격", "공정안전보고서 작성자 자격"),
    ("PSM 총사업기간", "공정안전보고서 총사업기간"),
    ("PSM 착공예정일", "공정안전보고서 착공예정일"),
    ("PSM 시운전기간", "공정안전보고서 시운전기간"),
    ("CAP 단위공장명", "화학사고예방관리계획서 단위공장명"),
    ("CAP 산업단지명", "화학사고예방관리계획서 산업단지명"),
    ("CAP 제출구분", "화학사고예방관리계획서 제출구분"),
    ("CAP 공동비상대응계획 수립 여부", "화학사고예방관리계획서 공동비상대응계획 수립 여부"),
    ("CAP 유사제도 심사결과 활용 여부", "화학사고예방관리계획서 유사제도 심사결과 활용 여부"),
    ("CAP 최근 3년간 화학사고 발생 여부", "화학사고예방관리계획서 최근 3년간 화학사고 발생 여부"),
    ("CAP 작성자 성명", "화학사고예방관리계획서 작성자 성명"),
    ("CAP 담당자 연락처", "화학사고예방관리계획서 담당자 연락처"),
    ("CAP 담당자 이메일", "화학사고예방관리계획서 담당자 이메일"),
)


@dataclass(frozen=True)
class CompanyFactSpec:
    label: str
    example: object
    required: str
    usage: str
    help_text: str
    field_keys: tuple[str, ...] = ()
    choices: tuple[str, ...] = ()


COMPANY_FACT_SPECS: tuple[CompanyFactSpec, ...] = (
    # Common / Stage-1 facts.
    CompanyFactSpec("사업장명", "한빛정밀화학(주) 울산공장 (가상)", "Y", "공통", "법정 서식에 사용할 실제 사업장명", ("business.company_name", "business.site_name")),
    CompanyFactSpec("사업장 주소", "울산광역시 남구 산업로 000 (가상)", "Y", "공통", "도로명주소 또는 법정 사업장 소재지", ("business.address",)),
    CompanyFactSpec("사업자등록번호", "123-45-67890 (가상)", "대상 시", "공통", "법정 서식에 기재되는 회사 고유번호", ("business.registration_no", "cap.business.registration_no")),
    CompanyFactSpec("대표자 성명", "홍길동 (가상)", "대상 시", "공통", "현재 대표자 성명", ("business.representative", "cap.business.representative")),
    CompanyFactSpec("업종 또는 주요 생산품", "석유화학계 기초화학물질 및 정밀화학 중간체 제조", "Y", "공통", "업종과 주요 생산품을 간단히 기재", ("business.main_products",)),
    CompanyFactSpec("한국표준산업분류(KSIC) 코드", "20111", "N", "공정안전보고서", "모르면 '모름' 가능. 시스템이 코드 자체를 추측해 확정하지 않음", ("business.ksic",)),
    CompanyFactSpec("대표전화", "052-000-0000 (가상)", "대상 시", "공통", "사업장 대표전화", ("business.phone", "cap.business.contact")),
    CompanyFactSpec("팩스번호", "052-000-0001 (가상)", "선택", "공정안전보고서", "팩스가 없으면 '해당없음'", ("business.fax",)),
    CompanyFactSpec("예상근무 근로자수", 120, "대상 시", "공정안전보고서", "해당 사업장의 예상 또는 현재 근로자수", ("business.employee_count",)),
    CompanyFactSpec("전기계약용량(kW)", 2500, "대상 시", "공정안전보고서", "전기사용계약 또는 시설자료의 계약용량", ("business.electric_contract_capacity",)),
    CompanyFactSpec("기존 공정안전보고서 보유 여부", "Y", "Y", "공통", "Y / N / 해당없음 / 모름", choices=("Y", "N", "해당없음", "모름")),
    CompanyFactSpec("기존 장외영향평가서 보유 여부", "Y", "Y", "화학사고예방관리계획서", "Y / N / 해당없음 / 모름", choices=("Y", "N", "해당없음", "모름")),
    CompanyFactSpec("기존 화학사고예방관리계획서 보유 여부", "N", "Y", "화학사고예방관리계획서", "Y / N / 해당없음 / 모름", choices=("Y", "N", "해당없음", "모름")),
    CompanyFactSpec("현재 목적", "신규 사전진단", "Y", "공통", "신규 사전진단 / 변경검토 / 재제출검토", choices=("신규 사전진단", "변경검토", "재제출검토")),

    # PSM (공정안전보고서) statutory-form facts. Narrative overview is
    # intentionally excluded: AI can draft it from confirmed
    # process/material/equipment evidence.
    CompanyFactSpec("공정안전보고서 사업 구분", "설치·이전", "대상 시", "공정안전보고서", "설치·이전 / 변경 / 기존설비 / 모름", ("psm.business.project_type",), ("설치·이전", "변경", "기존설비", "모름")),
    CompanyFactSpec("공정안전보고서 심사대상 설비명", "반응·정제 공정 (가상)", "대상 시", "공정안전보고서", "공정안전보고서 심사대상 설비의 회사 사용 명칭", ("psm.business.target_facility",)),
    CompanyFactSpec("공정안전보고서 부지면적(㎡)", 28500, "대상 시", "공정안전보고서", "사업장 부지면적", ("psm.business.site_area",)),
    CompanyFactSpec("공정안전보고서 주요건물(동/층/연면적)", "생산동 2동·3층·연면적 8,400㎡ (가상)", "대상 시", "공정안전보고서", "주요건물 수·층수·연면적 등 회사 확정값", ("psm.business.main_building",)),
    CompanyFactSpec("공정안전보고서 작성자 성명", "김안전 (가상)", "대상 시", "공정안전보고서", "최종 보고서 작성 책임자 성명"),
    CompanyFactSpec("공정안전보고서 작성자 자격", "산업안전기사 (가상)", "대상 시", "공정안전보고서", "법정 서식에 기재할 작성자 자격"),
    CompanyFactSpec("공정안전보고서 총사업기간", "2026.10~2027.06 (가상)", "대상 시", "공정안전보고서", "총 사업기간", ("psm.business.total_period",)),
    CompanyFactSpec("공정안전보고서 착공예정일", "2026-10-15 (가상)", "대상 시", "공정안전보고서", "착공 예정일", ("psm.business.start_date",)),
    CompanyFactSpec("공정안전보고서 시운전기간", "2027.05~2027.06 (가상)", "대상 시", "공정안전보고서", "시운전 예정기간", ("psm.business.commissioning_period",)),

    # CAP (화학사고예방관리계획서) statutory-form facts. Writing level and
    # impact-range conclusions are deliberately excluded because the
    # rule/analysis pipeline derives them.
    CompanyFactSpec("화학사고예방관리계획서 단위공장명", "제1생산공장 (가상)", "대상 시", "화학사고예방관리계획서", "계획서 작성 단위가 되는 단위공장명", ("cap.business.unit_plant_name",)),
    CompanyFactSpec("화학사고예방관리계획서 산업단지명", "울산미포국가산업단지 (가상)", "대상 시", "화학사고예방관리계획서", "산업단지 밖이면 '해당없음'", ("cap.business.industrial_complex",)),
    CompanyFactSpec("화학사고예방관리계획서 제출구분", "신규", "대상 시", "화학사고예방관리계획서", "신규 / 변경 / 재제출 / 모름", ("cap.business.submission_type",), ("신규", "변경", "재제출", "모름")),
    CompanyFactSpec("화학사고예방관리계획서 공동비상대응계획 수립 여부", "N", "대상 시", "화학사고예방관리계획서", "회사에서 수립 여부를 확인해 Y / N / 해당없음 / 모름", ("cap.business.joint_emergency_plan",), ("Y", "N", "해당없음", "모름")),
    CompanyFactSpec("화학사고예방관리계획서 유사제도 심사결과 활용 여부", "N", "대상 시", "화학사고예방관리계획서", "기존 유사제도 심사결과 활용 여부", ("cap.business.other_system_review",), ("Y", "N", "해당없음", "모름")),
    CompanyFactSpec("화학사고예방관리계획서 최근 3년간 화학사고 발생 여부", "N", "대상 시", "화학사고예방관리계획서", "회사 사고기록을 기준으로 Y / N / 모름", ("cap.business.recent_accident",), ("Y", "N", "모름")),
    CompanyFactSpec("화학사고예방관리계획서 작성자 성명", "이환경 (가상)", "대상 시", "화학사고예방관리계획서", "계획서 작성 담당자 성명", ("cap.business.writer_info",)),
    CompanyFactSpec("화학사고예방관리계획서 담당자 연락처", "010-0000-0000 (가상)", "대상 시", "화학사고예방관리계획서", "작성 담당자 연락처", ("cap.business.writer_contact",)),
    CompanyFactSpec("화학사고예방관리계획서 담당자 이메일", "safety@example.com (가상)", "대상 시", "화학사고예방관리계획서", "작성 담당자 이메일", ("cap.business.writer_email",)),
)


AI_DRAFT_EXCLUDED_LABELS: tuple[str, ...] = (
    "주요사업 내용 또는 변경내용",
    "공정개요",
    "화학사고예방관리계획서 작성수준",
    "총괄영향범위내 주민여부",
    "사고시나리오 설명",
    "위험성평가 서술",
)


def _norm(value: object) -> str:
    return re.sub(r"\s+", "", "" if value is None else str(value)).strip().lower()


def _business_value(business: Mapping[str, object], *labels: str) -> object:
    normalized = {_norm(key): value for key, value in business.items()}
    for label in labels:
        value = normalized.get(_norm(label))
        if value not in (None, ""):
            return value
    return ""


def _is_unknown(value: object) -> bool:
    return _norm(value) in UNKNOWN_TOKENS


def _set_project_fact(project: Any, key: str, label: str, value: object, evidence: Sequence[Any]) -> None:
    if value in (None, ""):
        return
    status = "HOLD" if _is_unknown(value) else ("VERIFIED" if evidence else "USER_CONFIRMED")
    project.set_field(key, label, value, status, evidence=list(evidence) if status != "HOLD" else [])


def _aliased_business(business: Mapping[str, Any]) -> dict[str, Any]:
    """Accept a pre-release workbook's PSM/CAP abbreviated column headers
    alongside the current full-name ones (see LABEL_ALIASES)."""
    values = dict(business)
    for old, current in LABEL_ALIASES:
        if current in values and old not in values:
            values[old] = values[current]
        elif old in values and current not in values:
            values[current] = values[old]
    return values


def seed_company_facts(project: Any, business: Mapping[str, object]) -> None:
    """Carry company-direct workbook facts into Stage 2 without inference."""
    business = _aliased_business(business)
    source = str(getattr(project, "stage1_source_fingerprint", "") or "").strip()
    evidence: list[Any] = []
    if source:
        from engine.stage2.project import EvidenceRef

        evidence = [
            EvidenceRef(
                source_type="STAGE1_WORKBOOK",
                source_name="회사 입력 Excel",
                sha256=source,
                note="회사가 직접 입력·확인한 고유 사실",
            )
        ]

    labels_by_key = {
        "business.company_name": "회사명",
        "business.site_name": "사업장명",
        "business.address": "사업장 소재지",
        "business.registration_no": "사업자등록번호",
        "cap.business.registration_no": "사업자등록번호",
        "business.representative": "대표자 성명",
        "cap.business.representative": "대표자 성명",
        "business.main_products": "주요 생산품·업종",
        "business.ksic": "한국표준산업분류 코드",
        "business.phone": "대표전화",
        "cap.business.contact": "대표전화",
        "business.fax": "팩스번호",
        "business.employee_count": "예상근무 근로자수",
        "business.electric_contract_capacity": "전기계약용량",
        "psm.business.project_type": "사업의 구분",
        "psm.business.target_facility": "심사대상 설비명",
        "psm.business.site_area": "부지면적",
        "psm.business.main_building": "주요건물",
        "psm.business.total_period": "총사업기간",
        "psm.business.start_date": "착공예정일",
        "psm.business.commissioning_period": "시운전기간",
        "cap.business.unit_plant_name": "단위공장명",
        "cap.business.industrial_complex": "산업단지",
        "cap.business.submission_type": "제출구분",
        "cap.business.joint_emergency_plan": "공동비상대응계획 수립 여부",
        "cap.business.other_system_review": "유사제도 심사결과 활용",
        "cap.business.recent_accident": "최근 3년간 화학사고 발생 여부",
        "cap.business.writer_info": "화학사고예방관리계획서 작성자",
        "cap.business.writer_contact": "담당자 연락처",
        "cap.business.writer_email": "담당자 메일주소",
    }

    for spec in COMPANY_FACT_SPECS:
        if not spec.field_keys:
            continue
        value = _business_value(business, spec.label)
        if value in (None, ""):
            continue
        for key in spec.field_keys:
            _set_project_fact(project, key, labels_by_key.get(key, spec.label), value, evidence)

    writer_name = _business_value(business, "공정안전보고서 작성자 성명")
    writer_qualification = _business_value(business, "공정안전보고서 작성자 자격")
    if writer_name not in (None, "") or writer_qualification not in (None, ""):
        payload = {
            "작성자": "" if writer_name is None else str(writer_name).strip(),
            "작성자 자격": "" if writer_qualification is None else str(writer_qualification).strip(),
        }
        if _is_unknown(writer_name) or _is_unknown(writer_qualification):
            project.set_field("psm.business.writer_info", "보고서 작성자", payload, "HOLD")
        else:
            project.set_field(
                "psm.business.writer_info",
                "보고서 작성자",
                payload,
                "VERIFIED" if evidence else "USER_CONFIRMED",
                evidence=list(evidence),
            )


