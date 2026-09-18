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

from .project import CONFIRMED_STATUSES, Stage2Project


READY = "READY"
ASK_COMPANY = "ASK_COMPANY"
LEGAL_ENGINE = "LEGAL_ENGINE"
CALCULATION = "CALCULATION"
EXTERNAL_ANALYSIS = "EXTERNAL_ANALYSIS"
CONDITIONAL = "CONDITIONAL"
RENDERER_GAP = "RENDERER_GAP"

STATE_LABELS = {
    READY: "작성 가능",
    ASK_COMPANY: "회사 확인 필요",
    LEGAL_ENGINE: "법령 DB·판정엔진 필요",
    CALCULATION: "계산 필요",
    EXTERNAL_ANALYSIS: "영향평가·GIS 필요",
    CONDITIONAL: "해당 시 작성",
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

    # 별지 제1호
    items.append(CAPFormCoverageItem(
        1, "사업장의 작성수준 구분", "단위공장별 최대보유량 산출",
        READY if facilities else ASK_COMPANY, "회사 설비자료",
        ("inventory.facilities",), "설비별 취급물질·설계용량·최대보유량",
    ))
    items.append(CAPFormCoverageItem(
        1, "사업장의 작성수준 구분", "유해화학물질별 물질구분·하위/상위 규정수량",
        LEGAL_ENGINE, "법령 DB", (),
        "CAS·농도와 현행 규정수량 DB",
        "회사 입력값이 아니라 현행 법령 기준으로 자동판정해야 하는 항목",
    ))
    items.append(CAPFormCoverageItem(
        1, "사업장의 작성수준 구분", "최대보유량 단위 정규화(ton)",
        RENDERER_GAP if _chemical_units_need_ton_conversion(project) else (READY if chemicals else ASK_COMPANY),
        "계산·출력엔진", ("inventory.chemicals",), "원자료의 수량과 단위",
        "kg 등으로 입력된 값을 ton 표기 칸에 그대로 쓰지 않도록 단위변환 검증 필요",
    ))
    items.append(CAPFormCoverageItem(
        1, "사업장의 작성수준 구분", "최종 작성수준 1군/2군",
        READY if project.cap_group in {"1군", "2군"} else LEGAL_ENGINE,
        "법령 판정결과", ("cap.business.writing_level",), "물질별 규정수량 비교결과",
    ))

    # 별지 제2호
    items.append(_company_item(
        project, 2, "변경내역 관리대장", "단위공장명",
        ("cap.business.unit_plant_name",), "회사 내부 단위공장명",
    ))
    items.append(CAPFormCoverageItem(
        2, "변경내역 관리대장", "접수번호·결과번호·변경이력",
        CONDITIONAL, "회사 제출이력", (),
        "기존 제출·변경 이력이 있는 경우 접수/결과번호 및 변경대장",
        "최초 신규제출 전이라면 미부여/해당없음 처리 여부를 서식 기준에 맞게 표시",
    ))

    # 별지 제3호
    for item, keys, req in (
        ("단위공장명", ("cap.business.unit_plant_name",), "회사 내부 단위공장명"),
        ("산업단지", ("cap.business.industrial_complex",), "산업단지 공식 명칭 또는 해당 없음"),
        ("제출구분·최초/부적합", ("cap.business.submission_type", "cap.business.submission_reason"), "제출유형과 하위 사유"),
        ("공동비상대응계획 수립 여부", ("cap.business.joint_emergency_plan",), "공동/단독 제출 여부"),
        ("유사제도 심사결과 활용", ("cap.business.other_system_review",), "PSM/안전성향상계획 활용 여부"),
        ("최근 3년간 화학사고 발생 여부", ("cap.business.recent_accident",), "최근 3년 사고 이력"),
        ("작성자·연락처·메일", ("cap.business.writer_name", "cap.business.writer_contact", "cap.business.writer_email"), "작성 담당자 신상정보"),
    ):
        items.append(_company_item(project, 3, "사업장 일반정보", item, keys, req))
    items.append(CAPFormCoverageItem(
        3, "사업장 일반정보", "총괄영향범위 내 주민 여부",
        READY if _has(project, "cap.business.residents_in_overall_range") else EXTERNAL_ANALYSIS,
        "영향평가 결과", ("cap.business.residents_in_overall_range",),
        "총괄영향범위와 주민 분포 결과",
    ))

    # 별지 제4~5호
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
        5, "세부 취급시설 개요", "단위공장 구성·공정개요·취급물질",
        READY if _has(project, "process.description") and facilities and chemicals else ASK_COMPANY,
        "회사 공정·설비자료",
        ("process.description", "inventory.facilities", "inventory.chemicals"),
        "공정 흐름과 단위공장별 설비·물질",
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
    items.append(CAPFormCoverageItem(
        6, "유해화학물질 목록 및 명세", "물질구분·고유번호",
        LEGAL_ENGINE, "법령 DB", (),
        "CAS·농도와 현행 유해화학물질 분류/고유번호 DB",
    ))
    items.append(CAPFormCoverageItem(
        6, "유해화학물질 목록 및 명세", "비중·폭발한계·독성구분·위험노출수준·TWA·증기압·부식성",
        ASK_COMPANY, "회사 보유 SDS/MSDS", ("psm.psi.msds",),
        "실제 제품 SDS/MSDS 또는 회사 승인 물성자료",
        "KOSHA 자동조회는 현재 핵심 흐름에서 제외하므로 회사 자료를 우선 사용",
    ))

    # 별지 제7호
    items.append(CAPFormCoverageItem(
        7, "유해화학물질의 유해성 정보", "인체·물리·환경 유해성 및 출처",
        ASK_COMPANY, "회사 보유 SDS/MSDS", ("psm.psi.msds",),
        "실제 제품 SDS/MSDS",
        "AI는 업로드된 SDS에서 요약할 수 있지만 근거 없는 유해성은 생성하지 않음",
    ))
    items.append(CAPFormCoverageItem(
        7, "유해화학물질의 유해성 정보", "대표물질 선정 사유",
        CALCULATION if chemicals else ASK_COMPANY, "선정 규칙·사고영향 우선순위",
        ("inventory.chemicals",), "취급량·유해성·사고시나리오 선정근거",
    ))

    # 별지 제8호
    items.append(CAPFormCoverageItem(
        8, "사업장 주변 환경 정보", "500m 내 보호대상 체크·목록·거리",
        EXTERNAL_ANALYSIS, "GIS/현장·공간자료",
        ("cap.site.surrounding_environment",),
        "사업장 경계와 보호대상 공간자료",
    ))

    # 별지 제9호
    process_conditions_ready = bool(facilities) and _all_rows_have(facilities, ("설계압력", "design pressure"))
    items.append(CAPFormCoverageItem(
        9, "장치·설비 목록 및 명세", "설계·운전 압력/온도·설계용량·취급량",
        READY if process_conditions_ready else ASK_COMPANY, "회사 설비명세",
        ("inventory.facilities",), "설비별 설계/운전조건",
    ))
    connection_ready = bool(facilities) and _all_rows_have(facilities, ("연결구 크기", "호칭경"))
    items.append(CAPFormCoverageItem(
        9, "장치·설비 목록 및 명세", "최대 연결구 크기",
        READY if connection_ready else ASK_COMPANY, "P&ID/배관명세",
        ("inventory.facilities", "documents.pid"), "누출 가능한 최대 연결구 크기",
    ))

    # 별지 제10호
    items.append(CAPFormCoverageItem(
        10, "확산방지설비 현황", "방류벽·방지턱·트렌치 현황",
        READY if _has(project, "cap.safety.dike_layout") else ASK_COMPANY,
        "회사 방유제/트렌치 자료", ("cap.safety.dike_layout",),
        "형태·치수·연결 설비",
    ))
    items.append(CAPFormCoverageItem(
        10, "확산방지설비 현황", "필요용량·유효용량·검토결과",
        CALCULATION, "법정 계산식", ("cap.safety.dike_layout",),
        "확산방지설비 치수와 적용 기준",
    ))

    # 별지 제11호
    detector_rows = _rows(project, "cap.safety.gas_detection", "psm.psi.gas_detection")
    items.append(CAPFormCoverageItem(
        11, "고정식 유해감지시설 명세", "감지대상·설치위치·경보설정값·경보기 위치",
        READY if detector_rows else ASK_COMPANY, "회사 감지기 명세",
        ("cap.safety.gas_detection",), "감지기 Tag와 설정값",
    ))
    detector_detail_ready = bool(detector_rows) and all(
        _row_value(row, "작동시간") not in (None, "")
        and _row_value(row, "연동여부") not in (None, "")
        and _row_value(row, "정밀도") not in (None, "")
        and _row_value(row, "유지관리") not in (None, "")
        for row in detector_rows
    )
    items.append(CAPFormCoverageItem(
        11, "고정식 유해감지시설 명세", "작동시간·측정방식·연동여부·정밀도·유지관리",
        READY if detector_detail_ready else ASK_COMPANY,
        "감지기 사양서/점검기준", ("cap.safety.gas_detection",),
        "제조사 사양 및 사업장 유지관리 기준",
    ))

    # 별지 제12~15호
    items.append(CAPFormCoverageItem(
        12, "사고시나리오 사업장 주변지역 영향 평가", "사고시나리오명·반경·장외거리·사고원점",
        EXTERNAL_ANALYSIS, "KORA/영향평가",
        ("cap.offsite.impact_range_result",),
        "확정된 누출조건·기상조건·영향평가 결과",
    ))
    items.append(CAPFormCoverageItem(
        12, "사고시나리오 사업장 주변지역 영향 평가", "주민수·산업단지 내외 구분·보호대상",
        EXTERNAL_ANALYSIS, "GIS/인구·보호대상 분석",
        ("cap.offsite.population_and_protected_targets",),
        "영향범위와 공간·인구자료",
    ))
    items.append(CAPFormCoverageItem(
        13, "총괄영향범위 사업장 주변지역 영향 평가", "총괄영향범위·보호대상 목록",
        CALCULATION, "별지 12 결과 통합",
        ("cap.offsite.impact_range_result", "cap.offsite.population_and_protected_targets"),
        "개별 사고시나리오 영향범위 결과",
    ))
    items.append(CAPFormCoverageItem(
        14, "사고시나리오별 시설빈도", "개시사건 개수·사고빈도 합계",
        CALCULATION, "설비구성 × 규정 빈도",
        ("inventory.facilities",),
        "사고구획별 설비·배관·플랜지·펌프 등 개수",
    ))
    items.append(CAPFormCoverageItem(
        15, "위험도 분석", "시나리오 수·시설빈도·장외거리·주민수·구간점수·위험도",
        CALCULATION, "별지 12·14 + 별표 3", (),
        "완성된 사고시나리오 영향평가와 시설빈도 결과",
    ))

    # 별지 제16호
    items.append(CAPFormCoverageItem(
        16, "비상대응분야 요약서", "사업장 일반정보·담당자 및 연락처",
        READY if _has(project, "cap.business.writer_name", "cap.business.writer_contact") else ASK_COMPANY,
        "사업장 일반정보 재사용",
        ("cap.business.writer_name", "cap.business.writer_contact"),
        "별지 3의 확정값",
    ))
    items.append(CAPFormCoverageItem(
        16, "비상대응분야 요약서", "작성일",
        RENDERER_GAP,
        "출력엔진",
        (),
        "사용자가 확정한 작성일 또는 출력일",
        "현재 초안에서 공란으로 남는 항목이므로 별도 날짜 필드/출력 규칙 필요",
    ))
    items.append(CAPFormCoverageItem(
        16, "비상대응분야 요약서", "사고시나리오·비상대응 핵심내용",
        CALCULATION, "별지 12~15 및 비상대응계획 요약", (),
        "완성된 사고시나리오·위험도·비상대응계획",
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
