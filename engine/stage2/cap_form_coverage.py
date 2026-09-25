from __future__ import annotations

"""CAP statutory-form coverage audit.

This answers not only whether Stage 2 has some supporting document, but whether
important statutory-form blocks can actually be populated without inventing a
company fact. Unknown company facts, legal lookup values, calculations and
impact/GIS results are reported separately instead of being silently blank.
"""

from dataclasses import asdict, dataclass
from collections.abc import Mapping, Sequence
from typing import Any

from .cap_chemical_legal import build_cap_chemical_legal_data
from .cap_sds_engine import build_cap_form6_sds_data, build_cap_form7_data
from .cap_form1_engine import build_cap_form1_data
from .cap_form2_engine import build_cap_form2_readiness
from .cap_form8_engine import build_cap_form8_data
from .cap_form9_engine import build_cap_form9_data
from .cap_form10_engine import build_cap_form10_data
from .cap_form11_engine import build_cap_form11_data
from .cap_impact_engine import build_cap_form12_data, build_cap_form13_data
from .cap_risk_engine import build_cap_form14_data, build_cap_form15_data
from .cap_form16_engine import build_cap_form16_data
from .project import CONFIRMED_STATUSES, Stage2Project


READY = "READY"
ASK_COMPANY = "ASK_COMPANY"
LEGAL_ENGINE = "LEGAL_ENGINE"
CALCULATION = "CALCULATION"
EXTERNAL_ANALYSIS = "EXTERNAL_ANALYSIS"
CONDITIONAL = "CONDITIONAL"
NOT_APPLICABLE = "NOT_APPLICABLE"
RENDERER_GAP = "RENDERER_GAP"

STATE_LABELS = {
    READY: "작성 가능",
    ASK_COMPANY: "회사 확인 필요",
    LEGAL_ENGINE: "법령 DB·판정엔진 필요",
    CALCULATION: "계산 필요",
    EXTERNAL_ANALYSIS: "영향평가·GIS 필요",
    CONDITIONAL: "해당 시 작성",
    NOT_APPLICABLE: "해당 없음",
    RENDERER_GAP: "출력엔진 보완 필요",
}


@dataclass(frozen=True)
class CAPFormCoverageItem:
    form_no: int
    form_name: str
    item: str
    state: str
    source_kind: str
    field_keys: tuple[str, ...] = ()
    required_input: str = ""
    note: str = ""

    @property
    def state_label(self) -> str:
        return STATE_LABELS.get(self.state, self.state)

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["state_label"] = self.state_label
        return raw


def _record(project: Stage2Project, key: str):
    rec = project.get_field(key)
    if rec is None or rec.status not in CONFIRMED_STATUSES:
        return None
    if rec.value in (None, ""):
        return None
    return rec


def _has(project: Stage2Project, *keys: str) -> bool:
    return all(_record(project, key) is not None for key in keys)


def _rows(project: Stage2Project, *keys: str) -> list[Mapping[str, Any]]:
    for key in keys:
        rec = _record(project, key)
        if rec is None or not isinstance(rec.value, list):
            continue
        rows = [dict(row) for row in rec.value if isinstance(row, Mapping)]
        if rows:
            return rows
    return []


def _norm_key(value: object) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _row_value(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_norm_key(k): v for k, v in row.items()}
    for alias in aliases:
        value = normalized.get(_norm_key(alias))
        if value not in (None, ""):
            return value
    return ""


def _all_rows_have(rows: Sequence[Mapping[str, Any]], aliases: tuple[str, ...]) -> bool:
    return bool(rows) and all(_row_value(row, *aliases) not in (None, "") for row in rows)


def _structured_rows(project: Stage2Project, key: str) -> list[Mapping[str, Any]]:
    rec = _record(project, key)
    if rec is None:
        return []
    if isinstance(rec.value, Mapping):
        return [dict(rec.value)]
    if isinstance(rec.value, list):
        return [dict(row) for row in rec.value if isinstance(row, Mapping)]
    return []


def _chemical_units_need_ton_conversion(project: Stage2Project) -> bool:
    rows = _rows(project, "inventory.chemicals", "cap.chemical.details")
    if not rows:
        return False
    for row in rows:
        unit = str(_row_value(row, "단위", "수량 단위", "quantity unit") or "").strip().lower()
        if unit and unit not in {"ton", "t", "톤"}:
            return True
    return False


def _company_item(
    project: Stage2Project,
    form_no: int,
    form_name: str,
    item: str,
    keys: tuple[str, ...],
    required_input: str,
    *,
    note: str = "",
) -> CAPFormCoverageItem:
    return CAPFormCoverageItem(
        form_no=form_no,
        form_name=form_name,
        item=item,
        state=READY if _has(project, *keys) else ASK_COMPANY,
        source_kind="회사 확정자료",
        field_keys=keys,
        required_input=required_input,
        note=note,
    )


def audit_cap_form_coverage(project: Stage2Project) -> tuple[CAPFormCoverageItem, ...]:
    if not project.cap_in_scope:
        return ()

    items: list[CAPFormCoverageItem] = []
    chemicals = _rows(project, "inventory.chemicals", "cap.chemical.details")
    facilities = _rows(project, "inventory.facilities", "cap.facility.equipment_specs")
    form1 = build_cap_form1_data(project)
    form2 = build_cap_form2_readiness(project)
    form6 = build_cap_chemical_legal_data(project)
    form6_sds = build_cap_form6_sds_data(project)
    form7 = build_cap_form7_data(project)
    form8 = build_cap_form8_data(project)
    form9 = build_cap_form9_data(project)
    form10 = build_cap_form10_data(project)
    form11 = build_cap_form11_data(project)
    form12 = build_cap_form12_data(project)
    form13 = build_cap_form13_data(project)
    form14 = build_cap_form14_data(project)
    form15 = build_cap_form15_data(project)
    form16 = build_cap_form16_data(project)
    threshold_rows_ready = bool(form1.chemical_rows) and all(
        str(row.get("물질구분") or "").strip()
        and str(row.get("하위규정수량(ton)") or "").strip()
        and str(row.get("상위규정수량(ton)") or "").strip()
        for row in form1.chemical_rows
    )
    quantity_rows_ready = bool(form1.chemical_rows) and all(
        str(row.get("사업장 내 최대보유량(ton)") or "").strip()
        for row in form1.chemical_rows
    )
    facility_quantity_ready = bool(form1.facility_rows) and all(
        str(row.get("취급량(ton)") or "").strip()
        for row in form1.facility_rows
    )

    # 별지 제1호
    items.append(CAPFormCoverageItem(
        1, "사업장의 작성수준 구분", "단위공장별 최대보유량 산출",
        READY if facility_quantity_ready else ASK_COMPANY, "회사 설비자료 + 단위정규화 엔진",
        ("inventory.facilities",), "설비별 취급물질·설계용량·최대보유량",
    ))
    items.append(CAPFormCoverageItem(
        1, "사업장의 작성수준 구분", "유해화학물질별 물질구분·하위/상위 규정수량",
        READY if threshold_rows_ready else LEGAL_ENGINE, "Stage 1 CAP 승인 법령 DB", (),
        "CAS·농도와 현행 규정수량 DB",
        "Stage 1의 별표 3→별표 2 우선순위 법령판정 로직을 Stage 2에서 재사용",
    ))
    items.append(CAPFormCoverageItem(
        1, "사업장의 작성수준 구분", "최대보유량 단위 정규화(ton)",
        READY if quantity_rows_ready else ASK_COMPANY,
        "회사 수량·단위 + ton 정규화 엔진", ("inventory.chemicals",), "원자료의 최대보유량과 질량단위",
        "kg·ton·g는 자동 환산하며 환산할 수 없는 단위는 회사 확인이 필요함",
    ))
    items.append(CAPFormCoverageItem(
        1, "사업장의 작성수준 구분", "최종 작성수준 1군/2군",
        READY if project.cap_group in {"1군", "2군"} else LEGAL_ENGINE,
        "법령 판정결과", ("cap.business.writing_level",), "물질별 규정수량 비교결과",
    ))

    # 별지 제2호
    if form2.status == "NOT_APPLICABLE":
        form2_state = NOT_APPLICABLE
        form2_source = "확정된 제출구분"
        form2_note = form2.messages[0] if form2.messages else "최초 신규제출로 변경내역 관리대장 비적용"
    elif form2.status == "PASS":
        form2_state = READY
        form2_source = "회사 확정 변경내역"
        form2_note = form2.messages[0] if form2.messages else "변경내역 관리대장 확인 완료"
    else:
        form2_state = ASK_COMPANY
        form2_source = "회사 제출유형·변경이력 확인"
        form2_note = " / ".join(form2.blockers)

    items.append(CAPFormCoverageItem(
        2, "변경내역 관리대장", "제출유형에 따른 적용 여부",
        form2_state,
        form2_source,
        ("cap.business.submission_type", "cap.business.submission_reason", "cap.prevention.change_log"),
        "제출구분·사유와 변경내역 관리대장",
        form2_note,
    ))
    items.append(CAPFormCoverageItem(
        2, "변경내역 관리대장", "변경내역 필수항목",
        form2_state,
        "회사 확정 변경내역",
        ("cap.prevention.change_log",),
        "일자, 변경항목, 변경의 종류, 변경 전·후 내용, 후속조치, 담당자",
        form2_note,
    ))

    # 별지 제3호
    items.append(_company_item(
        project, 3, "사업장 일반정보", "사업자등록번호·대표자·주소·대표전화",
        ("cap.business.registration_no", "cap.business.representative", "business.address", "cap.business.contact"),
        "사업자등록번호, 대표자, 사업장 주소, 대표전화",
    ))
    unit_plant_ready = _has(project, "cap.business.unit_plant_name") or bool(str(project.site_name or "").strip())
    items.append(CAPFormCoverageItem(
        3, "사업장 일반정보", "단위공장명",
        READY if unit_plant_ready else ASK_COMPANY,
        "회사 확정자료", ("cap.business.unit_plant_name",),
        "회사 내부 단위공장명",
    ))
    for item, keys, req in (
        ("산업단지", ("cap.business.industrial_complex",), "산업단지 공식 명칭 또는 해당 없음"),
        ("제출구분·최초/부적합", ("cap.business.submission_type", "cap.business.submission_reason"), "제출유형과 하위 사유"),
        ("공동비상대응계획 수립 여부", ("cap.business.joint_emergency_plan",), "공동/단독 제출 여부"),
        ("유사제도 심사결과 활용", ("cap.business.other_system_review",), "PSM/안전성향상계획 활용 여부"),
        ("최근 3년간 화학사고 발생 여부", ("cap.business.recent_accident",), "최근 3년 사고 이력"),
    ):
        items.append(_company_item(project, 3, "사업장 일반정보", item, keys, req))
    writer_ready = (
        (_has(project, "cap.business.writer_name") or _has(project, "cap.business.writer_info"))
        and _has(project, "cap.business.writer_contact")
        and _has(project, "cap.business.writer_email")
    )
    items.append(CAPFormCoverageItem(
        3, "사업장 일반정보", "작성자·연락처·메일",
        READY if writer_ready else ASK_COMPANY,
        "회사 확정자료",
        ("cap.business.writer_name", "cap.business.writer_info", "cap.business.writer_contact", "cap.business.writer_email"),
        "작성 담당자 신상정보",
    ))
    items.append(CAPFormCoverageItem(
        3, "사업장 일반정보", "작성수준 1군/2군",
        READY if (project.cap_group in {"1군", "2군"} or _has(project, "cap.business.writing_level")) else LEGAL_ENGINE,
        "Stage 1 판정결과 또는 회사 확인값", ("cap.business.writing_level",),
        "확정된 작성수준",
    ))
    overall_rows = _structured_rows(project, "cap.offsite.overall_impact_summary")
    residents_ready = _has(project, "cap.business.residents_in_overall_range") or any(
        _row_value(row, "총괄영향범위 내 거주민수", "거주민수", "총괄 거주민수") not in (None, "")
        for row in overall_rows
    )
    items.append(CAPFormCoverageItem(
        3, "사업장 일반정보", "총괄영향범위 내 주민 여부",
        READY if residents_ready else EXTERNAL_ANALYSIS,
        "영향평가 결과", ("cap.business.residents_in_overall_range", "cap.offsite.overall_impact_summary"),
        "총괄영향범위와 주민 분포 결과",
    ))

    # 별지 제4~5호
    items.append(_company_item(
        project, 4, "총괄 취급시설 개요", "총괄 시설구성·공정개요",
        ("cap.basic.total_facility_overview", "process.description"),
        "총괄 취급시설 구성과 공정개요",
    ))
    items.append(CAPFormCoverageItem(
        4, "총괄 취급시설 개요", "장치·설비 종류 및 수량",
        READY if facilities else ASK_COMPANY, "설비목록 자동집계",
        ("inventory.facilities",), "설비종류가 구조화된 설비목록",
        "설비목록에서 유형별 수량을 집계해 체크박스와 기수를 자동작성",
    ))
    items.append(_company_item(
        project, 4, "총괄 취급시설 개요", "입·출하 및 운반시설",
        ("cap.basic.loading_transport",), "입·출하시설 및 보유 탱크로리 수",
    ))
    items.append(CAPFormCoverageItem(
        4, "총괄 취급시설 개요", "유해화학물질 및 최대보유량",
        READY if chemicals else ASK_COMPANY,
        "별지 제1호 물질·최대보유량 결과 재사용",
        ("inventory.chemicals",),
        "유해화학물질명·CAS·최대보유량",
    ))
    items.append(CAPFormCoverageItem(
        5, "세부 취급시설 개요", "단위공장 구성·공정개요·취급물질",
        READY if _has(project, "cap.basic.unit_facility_overview")
        and _has(project, "process.description") and facilities and chemicals else ASK_COMPANY,
        "회사 공정·설비자료",
        ("cap.basic.unit_facility_overview", "process.description", "inventory.facilities", "inventory.chemicals"),
        "단위공장 구성, 공정 흐름과 단위공장별 설비·물질",
    ))
    items.append(_company_item(
        project, 5, "세부 취급시설 개요", "입·출하 및 운반시설",
        ("cap.basic.loading_transport",), "입·출하시설 및 보유 탱크로리 수",
    ))

    # 별지 제6호
    identification_ready = (
        bool(chemicals)
        and _all_rows_have(chemicals, ("CAS 번호", "CAS No.", "CAS"))
        and _all_rows_have(chemicals, ("함량(%)", "함량", "농도(%)"))
        and _all_rows_have(chemicals, ("물리적 상태", "물질상태", "성상"))
    )
    items.append(CAPFormCoverageItem(
        6, "유해화학물질 목록 및 명세", "물질명·CAS·함량·상태",
        READY if identification_ready else ASK_COMPANY, "회사 화학물질표/SDS",
        ("inventory.chemicals",), "회사 화학물질 목록 및 제품 SDS",
    ))
    form6_legal_ready = bool(form6.rows) and all(
        str(row.get("물질구분") or "").strip() and str(row.get("고유번호") or "").strip()
        for row in form6.rows
    ) and not form6.blockers
    items.append(CAPFormCoverageItem(
        6, "유해화학물질 목록 및 명세", "물질구분·고유번호",
        READY if form6_legal_ready else LEGAL_ENGINE,
        "현행 별표 2 고유번호 + 별표 2·3 법적 물질구분", (),
        "CAS·농도와 현행 유해화학물질 분류/고유번호 DB",
        "사고대비물질 별표 3 연번은 고유번호로 대체하지 않음",
    ))
    items.append(CAPFormCoverageItem(
        6, "유해화학물질 목록 및 명세", "비중·폭발한계·독성구분·위험노출수준·TWA·증기압·부식성",
        READY if form6_sds.ready else ASK_COMPANY,
        "회사 제품 SDS 전사값", ("cap.chemical.details",),
        "물질별 SDS 물성값, SDS 파일명, SDS 작성·개정일",
        "외부/KOSHA MSDS 자동조회 없이 회사가 확인한 제품 SDS 값만 사용",
    ))

    # 별지 제7호
    items.append(CAPFormCoverageItem(
        7, "유해화학물질의 유해성 정보", "인체·물리·환경 유해성 및 출처",
        READY if form7.ready else ASK_COMPANY,
        "회사 제품 SDS/승인 유해성자료", ("cap.chemical.hazard_information",),
        "대표물질의 인체·물리·환경 유해성, 출처, SDS 파일명·개정일",
        "법적 고유번호와 최대보유량은 별지 제6호·제1호 결과를 재사용",
    ))
    items.append(CAPFormCoverageItem(
        7, "유해화학물질의 유해성 정보", "대표물질 선정 사유",
        READY if form7.ready else ASK_COMPANY,
        "회사/사고시나리오 선정근거", ("cap.chemical.hazard_information",),
        "대표물질을 선택한 실제 회사·사고시나리오 근거",
        "화학물질 목록만으로 프로그램이 대표물질을 임의 선택하지 않음",
    ))

    # 별지 제8호
    items.append(CAPFormCoverageItem(
        8, "사업장 주변 환경 정보", "500m 내 보호대상 체크·목록·거리",
        READY if form8.ready else EXTERNAL_ANALYSIS,
        "회사/GIS/현장 확인자료 + 검증엔진",
        ("cap.site.surrounding_environment",),
        "보호대상 없음 여부 또는 보호대상 명칭·구분·세부유형·위치·경계거리·검색 출처·GIS/현장 근거·500m 전체 검토 확인",
        "검색 후보만으로 법정 거리·별표 4 분류·대상 누락 여부를 확정하지 않음; 500m 초과값·근거 없는 위치/거리는 보류",
    ))

    # 별지 제9호
    form9_data_ready = bool(form9.rows) and not form9.blockers
    items.append(CAPFormCoverageItem(
        9, "장치·설비 목록 및 명세", "설계·운전 압력/온도·설계용량·취급량",
        READY if form9_data_ready else ASK_COMPANY,
        "회사 설비명세 + 법정 단위 정규화",
        ("inventory.facilities",),
        "설비별 설계/운전조건과 최대보유량",
        "kg→ton, L→m3, kPa/bar→MPa를 정규화하고 유량단위는 설계용량(m3)에 복사하지 않음",
    ))
    connection_ready = bool(form9.rows) and all(
        str(row.get("연결구 크기(mm)") or "").strip() for row in form9.rows
    )
    items.append(CAPFormCoverageItem(
        9, "장치·설비 목록 및 명세", "최대 연결구 크기",
        READY if connection_ready else ASK_COMPANY,
        "P&ID/배관명세 또는 회사 확인",
        ("inventory.facilities", "documents.pid"),
        "누출 가능한 최대 연결구 크기(mm)",
    ))

    # 별지 제10호
    items.append(CAPFormCoverageItem(
        10, "확산방지설비 현황", "배치도·현장 증빙",
        READY if _has(project, "cap.safety.dike_layout") else ASK_COMPANY,
        "회사 방유제/트렌치 배치도", ("cap.safety.dike_layout",),
        "확산방지설비 위치·형태와 대상 취급시설을 확인할 수 있는 도면",
        "계산표와 도면 증빙을 별도 필드로 유지하여 첨부파일 HOLD가 계산자료를 덮어쓰지 않음",
    ))
    items.append(CAPFormCoverageItem(
        10, "확산방지설비 현황", "필요용량·유효용량·검토결과",
        READY if form10.ready else CALCULATION,
        "회사 확인 적용기준 + 치수계산 엔진",
        ("cap.safety.dike_calculation",),
        "필요용량 기준·근거, 내부치수·차감용적 또는 직접확인 유효용량",
        "유효용량만 산술계산하며 필요용량에 일률적인 임의 비율을 적용하지 않음",
    ))

    # 별지 제11호
    items.append(CAPFormCoverageItem(
        11, "고정식 유해감지시설 명세", "고정식 대상선별·감지대상·설치위치·경보설정값",
        READY if form11.rows and not form11.blockers else ASK_COMPANY,
        "회사 감지기 명세 + 고정식 대상선별",
        ("cap.safety.gas_detection",),
        "감지기 Tag, 설치형태, 감지대상, 설치위치, 경보설정값",
        "휴대식은 회사자료에는 유지하되 별지 제11호 자동기입 대상에서 제외",
    ))
    items.append(CAPFormCoverageItem(
        11, "고정식 유해감지시설 명세", "작동시간·측정방식·연동여부·정밀도·유지관리",
        READY if form11.ready else ASK_COMPANY,
        "제조사 사양서/점검기준 + 회사 연동정보",
        ("cap.safety.gas_detection",),
        "작동시간, 센서 측정원리, 연동 설비·조치, 정밀도, 점검·교정주기",
        "고정식/휴대식은 설치형태이며 측정방식과 별개로 관리",
    ))

    # 별지 제12~15호
    items.append(CAPFormCoverageItem(
        12, "사고시나리오 사업장 주변지역 영향 평가", "사고시나리오·장외거리·주민수·보호대상·사고원점",
        READY if form12.ready else EXTERNAL_ANALYSIS,
        "KORA/영향평가 + GIS 검증엔진",
        ("cap.offsite.scenario_impact_table",),
        "시나리오별 물질·설비·사고유형·장외거리·거주민/근로자·보호대상 수·사고원점·근거",
        "회사 화학물질/설비목록과 교차검증하며 AI가 공간값을 생성하지 않음",
    ))
    items.append(CAPFormCoverageItem(
        13, "총괄영향범위 사업장 주변지역 영향 평가", "총괄영향범위 확정요약·보호대상 목록·결과파일",
        READY if form13.ready else EXTERNAL_ANALYSIS,
        "GIS/KORA 확정결과 + 보호대상 공간중첩",
        ("cap.offsite.overall_impact_summary", "cap.offsite.population_and_protected_targets", "documents.kora_impact_result"),
        "총괄영향범위 산출방법/결과요약, 보호대상 명세, KORA/GIS 결과파일",
        "개별 장외거리 최대값으로 총괄영향범위 형상을 대체하지 않음",
    ))

    items.append(CAPFormCoverageItem(
        14, "사고시나리오별 시설빈도", "개시사건 개수·사고빈도·시나리오 시설빈도",
        READY if (form14.ready or form15.no_offsite_scenario) else CALCULATION,
        "P&ID·설비 개수 × 현행 별지 제14호 기준빈도",
        ("cap.offsite.scenario_frequency",),
        "시나리오별 10개 개시사건 개수와 개수 산정근거",
        "공식 CAP_DRAFT가 CURRENT일 때만 기준빈도 자동적용",
    ))
    items.append(CAPFormCoverageItem(
        15, "위험도 분석", "A·B·C·D 합계·구간점수·사고빈도/영향점수",
        READY if form15.ready else CALCULATION,
        "별지 12·14 + 별표 3",
        ("cap.offsite.scenario_impact_table", "cap.offsite.scenario_frequency"),
        "KORA/GIS 결과와 완성된 시설빈도",
        "증감 전 점수는 자동계산하되 최종 위험도는 안전원 결정 전에는 확정하지 않음",
    ))

    # 별지 제16호
    items.append(CAPFormCoverageItem(
        16, "비상대응분야 요약서", "사업장 일반정보·담당자 및 연락처",
        READY if not any("사업장 일반정보" in item for item in form16.company_blockers) else ASK_COMPANY,
        "별지 제3호 회사 확정정보 재사용",
        ("cap.business.representative", "business.address", "cap.business.registration_no",
         "cap.business.writer_name", "cap.business.writer_contact", "cap.business.writer_email"),
        "대표자·주소·사업자등록번호·담당자·연락처·메일",
    ))
    items.append(CAPFormCoverageItem(
        16, "비상대응분야 요약서", "작성일",
        READY,
        "DOCX 출력엔진",
        ("cap.business.report_date",),
        "회사 확정 작성일이 있으면 해당 날짜, 없으면 DOCX 생성일",
        "작성일 공란을 남기지 않되 회사가 별도 작성일을 확정하면 그 값을 우선 사용",
    ))
    items.append(CAPFormCoverageItem(
        16, "비상대응분야 요약서", "사고시나리오 선정 물질·사고유형",
        READY if form16.ready else (ASK_COMPANY if form16.company_blockers else CALCULATION),
        "별지 제1·12호 연계 계산",
        ("inventory.chemicals", "cap.offsite.scenario_impact_table"),
        "CAS·함량·최대보유량과 확정 사고유형",
        "별지 제12호 사고유형을 재사용하여 기존 사고유형 공란을 방지",
    ))
    items.append(CAPFormCoverageItem(
        16, "비상대응분야 요약서", "사고시나리오·위험도 핵심정보",
        READY if form16.ready else (ASK_COMPANY if form16.company_blockers else CALCULATION),
        "별지 제12·15호 연계 계산",
        ("cap.offsite.scenario_impact_table", "cap.offsite.scenario_frequency"),
        "시나리오명·설비·사고유형·시설빈도·장외거리·주민수·KORA/GIS 근거",
    ))
    items.append(CAPFormCoverageItem(
        16, "비상대응분야 요약서", "내부·외부 비상대응 핵심내용",
        READY if form16.ready else (ASK_COMPANY if form16.company_blockers else CALCULATION),
        "확정 비상대응계획 요약",
        ("cap.prevention.emergency_contact_system", "cap.internal.shutdown_authority",
         "cap.internal.shutdown_procedure", "cap.internal.communication_system"),
        "내부 비상대응 필수계획과 1군의 외부 비상대응계획",
        "AI 생성문이 아니라 회사 확정 비상대응자료를 항목별로 재배치",
    ))

    return tuple(items)


def summarize_cap_form_coverage(project: Stage2Project) -> dict[str, Any]:
    items = audit_cap_form_coverage(project)
    counts: dict[str, int] = {state: 0 for state in STATE_LABELS}
    for item in items:
        counts[item.state] = counts.get(item.state, 0) + 1
    ready = counts.get(READY, 0)
    return {
        "total": len(items),
        "ready": ready,
        "unresolved": len(items) - ready,
        "counts": counts,
        "items": [item.to_dict() for item in items],
    }
