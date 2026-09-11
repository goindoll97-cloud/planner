from __future__ import annotations

"""Plain-language consulting guidance used by company-facing screens.

The rule engine decides applicability.  This module does not decide legal
applicability; it explains *why* a fact is being requested, what the term means,
what the user can look at inside the company, and where the legal basis lives.

Company-facing UI should prefer this guidance over exposing raw rule-engine
terms such as APP1/APP2/APP3/APP4 or internal status codes.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConsultingGuide:
    key: str
    title: str
    plain_language: str
    why_needed: str
    what_to_check: tuple[str, ...] = field(default_factory=tuple)
    example: str = ""
    legal_basis: str = ""
    if_unknown: str = "모르면 추정하지 말고 '모름' 또는 '확인 필요'로 두어 판정을 보류합니다."
    decision_effect: str = ""


GUIDES: dict[str, ConsultingGuide] = {
    "PSM_R_RATIO": ConsultingGuide(
        key="PSM_R_RATIO",
        title="PSM 규정량 비율(R)이 무엇인가요?",
        plain_language=(
            "PSM 별표 13 대상물질의 실제 제조·취급량 또는 저장량을 각 물질의 법정 규정량과 비교해 만든 비율입니다. "
            "여러 대상물질이 있으면 법에서 정한 방식으로 비율을 합산합니다."
        ),
        why_needed="PSM 수량기준을 충족하는지 먼저 선별하기 위해 필요합니다.",
        what_to_check=(
            "회사 화학물질 목록의 하루 최대 제조·취급량",
            "최대 저장량",
            "제품 함량 또는 순도",
        ),
        example="R=1.20이면 현재 확인된 수량기준 합계가 기준의 120%라는 뜻입니다. 다만 이것만으로 최종 PSM 대상이 확정되는 것은 아닙니다.",
        legal_basis="「산업안전보건법 시행령」 제43조 및 별표 13(규정량·합산 관련 비고 포함)",
        decision_effect="R이 기준 이상이면 업종·제외설비·특수조건 등 다음 법적 조건을 계속 확인합니다.",
    ),
    "PSM_EXCLUDED_FACILITY": ConsultingGuide(
        key="PSM_EXCLUDED_FACILITY",
        title="PSM 제외설비가 무엇인가요?",
        plain_language=(
            "수량기준에 걸리더라도 법에서 PSM 적용대상에서 제외하도록 정한 특정 종류의 설비가 있습니다. "
            "회사의 설비가 그 유형에 실제로 해당하는지 확인하는 단계입니다."
        ),
        why_needed="PSM 수량기준을 충족한 뒤에도 법정 제외설비이면 최종 적용 여부가 달라질 수 있기 때문입니다.",
        what_to_check=(
            "원자력 설비",
            "군사시설",
            "사업장 내 직접 사용을 위한 난방용 연료의 저장·사용설비",
            "도매·소매시설",
            "차량 등의 운송설비",
            "LPG 충전·저장시설",
            "도시가스 공급시설",
            "그 밖에 고용노동부장관이 고시하는 제외설비",
        ),
        legal_basis="「산업안전보건법 시행령」 제43조제2항",
        decision_effect="해당한다고 답해도 즉시 제외 확정하지 않고, 선택한 제외유형이 실제 관련 공정·설비 범위 전체에 적용되는지 확인합니다.",
    ),
    "CAP_MAX_HOLDING": ConsultingGuide(
        key="CAP_MAX_HOLDING",
        title="사업장 최대보유량이 무엇인가요?",
        plain_language=(
            "같은 유해화학물질이 사업장 안의 여러 제조·사용·저장·보관시설에 동시에 존재할 수 있을 때, "
            "그 물질이 어느 한 순간 사업장에 최대로 존재할 수 있는 양을 법정 방식으로 산정한 값입니다."
        ),
        why_needed="화학사고예방관리계획서의 하위·상위 규정수량과 비교해 적용 가능성을 판단하기 위해 필요합니다.",
        what_to_check=(
            "해당 물질이 들어가는 제조·사용시설",
            "저장탱크",
            "보관시설",
            "각 시설의 설계용량·밀도·보관량 등 산정에 필요한 값",
        ),
        example=(
            "같은 물질이 저장탱크와 반응기에 동시에 존재할 수 있다면 한쪽 재고만 보는 것이 아니라 관련 시설을 함께 고려합니다. "
            "실제 법정값은 시설유형별 산정방법을 적용합니다."
        ),
        legal_basis="「유해화학물질의 규정수량에 관한 규정」 제2조제2호, 제4조 및 별표 4",
        decision_effect="확인된 최대보유량을 해당 물질의 하위·상위 규정수량과 비교해 비대상/하위기준/상위기준 검토로 진행합니다.",
    ),
    "CAP_APP1_SDS": ConsultingGuide(
        key="CAP_APP1_SDS",
        title="왜 SDS 유해성·위험성 분류를 확인하나요?",
        plain_language=(
            "화학사고예방관리계획서의 규정수량 기준 중에는 CAS 번호 목록으로만 판단할 수 없는 유해성·위험성 그룹 기준이 있습니다. "
            "따라서 물질별 직접목록에서 결론이 나지 않은 경우 SDS의 유해성·위험성 분류를 확인해야 합니다."
        ),
        why_needed="CAS 직접목록에서 찾지 못했다는 이유만으로 비대상으로 잘못 판단하는 것을 막기 위해 필요합니다.",
        what_to_check=(
            "SDS 제2항 유해성·위험성",
            "급성독성 등급",
            "인화성 등 물리·화학적 위험성 분류",
            "수생환경 유해성 분류",
        ),
        legal_basis="「유해화학물질의 규정수량에 관한 규정」 제3조 및 별표 1",
        decision_effect="SDS 분류가 확인되면 별표 1의 해당 유해성 그룹·구분과 규정수량을 연결합니다.",
    ),
    "CAP_BROAD_SCOPE": ConsultingGuide(
        key="CAP_BROAD_SCOPE",
        title="왜 CAS 번호만으로 판단할 수 없는 경우가 있나요?",
        plain_language=(
            "일부 법정 항목은 하나의 CAS 번호가 아니라 염류, 화합물군, 혼합물, 반응생성물처럼 더 넓은 물질범위를 규제합니다. "
            "이 경우 CAS 불일치만으로 비대상이라고 결론내리면 안 됩니다."
        ),
        why_needed="법적 물질범위에 실제 포함되는지 별도로 확인하기 위해 필요합니다.",
        what_to_check=(
            "제품 SDS의 성분명과 CAS",
            "염 또는 화합물 형태인지",
            "혼합물·반응생성물 여부",
            "법정 항목에 명시된 포함·제외조건",
        ),
        decision_effect="범위 포함 여부가 확인되기 전까지는 판정보류로 유지합니다.",
    ),
    "DECISION_HOLD": ConsultingGuide(
        key="DECISION_HOLD",
        title="'판정보류'는 무슨 뜻인가요?",
        plain_language=(
            "현재 정보만으로 대상 또는 비대상을 안전하게 확정할 수 없다는 뜻입니다. "
            "대상이라는 뜻도, 비대상이라는 뜻도 아닙니다."
        ),
        why_needed="법적 판단에 필요한 사실을 프로그램이 추정해서 잘못된 결론을 내리지 않도록 하기 위한 안전장치입니다.",
        what_to_check=(
            "화학물질 함량·순도",
            "실제 수량 또는 최대보유량",
            "SDS 분류",
            "시설 유형·제외조건",
            "법령 또는 승인 DB 최신상태",
        ),
        decision_effect="표시된 미확인 항목만 추가 확인한 뒤 다시 판정합니다.",
    ),
}


def get_guide(key: str) -> ConsultingGuide | None:
    return GUIDES.get(str(key or "").strip())


def all_guides() -> tuple[ConsultingGuide, ...]:
    return tuple(GUIDES.values())
