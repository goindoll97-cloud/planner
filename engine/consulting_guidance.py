from __future__ import annotations

"""Plain-language consulting guidance used by company-facing screens.

The rule engine decides applicability. This module does not decide legal
applicability; it explains why a fact is being requested, what the term means,
what the user can look at inside the company, and where the legal basis lives.

Company-facing UI should prefer this guidance over exposing raw rule-engine
terms such as APP1/APP2/APP3/APP4 or internal status codes.

Important UX rule: when a statute or decree delegates a concrete criterion to a
ministerial notice, guidance should follow that delegation to the current
approved notice whenever possible. If the delegated rule has not been verified,
the UI must show the exact delegated source to check rather than inventing an
answer.
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
    legal_hierarchy: tuple[str, ...] = field(default_factory=tuple)
    resolved_detail: str = ""
    source_status: str = ""
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
        legal_hierarchy=(
            "상위 근거: 「산업안전보건법」 제44조",
            "세부 대상·규정량: 「산업안전보건법 시행령」 제43조 및 별표 13",
        ),
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
            "「액화석유가스의 안전관리 및 사업법」에 따른 LPG 충전·저장시설",
            "「도시가스사업법」에 따른 가스공급시설",
            "비상발전기용 경유의 저장탱크 및 사용설비",
        ),
        example=(
            "예를 들어 비상발전기를 돌리기 위해 따로 설치한 경유 저장탱크와 그 사용설비는 시행령의 '그 밖에 고시하는 설비'를 "
            "구체화한 현행 고시상 적용제외 설비입니다."
        ),
        legal_basis="「산업안전보건법 시행령」 제43조제2항",
        legal_hierarchy=(
            "상위 규정: 「산업안전보건법 시행령」 제43조제2항제8호 — 고용노동부장관이 피해 정도가 크지 않다고 인정하여 고시하는 설비",
            "구체화 규정: 「공정안전보고서의 제출·심사·확인 및 이행상태평가 등에 관한 규정」 제2조의2",
        ),
        resolved_detail=(
            "현행 고용노동부고시 제2025-30호 제2조의2는 시행령 제43조제2항제8호의 설비를 "
            "'비상발전기용 경유의 저장탱크 및 사용설비'로 구체화하고 있습니다."
        ),
        source_status="현행 공식 행정규칙 확인",
        decision_effect="해당한다고 답해도 즉시 제외 확정하지 않고, 선택한 제외유형이 실제 관련 공정·설비 범위에 적용되는지 확인합니다.",
    ),
    "PSM_SPECIAL_CONDITION": ConsultingGuide(
        key="PSM_SPECIAL_CONDITION",
        title="왜 물성이나 별도 성분조건을 추가로 확인하나요?",
        plain_language=(
            "PSM 별표 13에는 CAS 번호만 같다고 자동으로 적용할 수 없는 항목이 있습니다. "
            "인화성 가스·인화성 액체처럼 물성으로 정해지는 항목이나, 특정 성분함량 조건이 붙은 항목은 회사 자료를 추가로 확인해야 합니다."
        ),
        why_needed="CAS 일치만으로 법정 항목을 잘못 적용하거나 제외하는 것을 막기 위해 필요합니다.",
        what_to_check=(
            "SDS의 물리적·화학적 특성 및 인화점",
            "제품의 실제 성분함량 또는 순도",
            "공정조건에서의 상태와 취급조건",
        ),
        legal_basis="「산업안전보건법 시행령」 별표 13의 해당 물질 행 및 비고",
        decision_effect="조건이 확인된 물질만 해당 별표 13 항목의 규정량 계산에 반영합니다.",
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
        legal_hierarchy=(
            "정의: 「유해화학물질의 규정수량에 관한 규정」 제2조제2호",
            "시설유형별 계산방법: 같은 규정 제4조 및 별표 4",
        ),
        decision_effect="확인된 최대보유량을 해당 물질의 하위·상위 규정수량과 비교해 비대상/하위기준/상위기준 검토로 진행합니다.",
    ),
    "CAP_SPECIAL_CONDITION": ConsultingGuide(
        key="CAP_SPECIAL_CONDITION",
        title="왜 물질의 상태나 특수조건을 확인하나요?",
        plain_language=(
            "화학사고예방관리계획서 규정수량표에는 같은 물질이라도 농도나 상온·상압 상태 등에 따라 다른 규정수량을 적용하는 경우가 있습니다. "
            "따라서 CAS 번호만으로 임의 선택하지 않고 실제 상태를 확인합니다."
        ),
        why_needed="잘못된 규정수량을 적용하지 않기 위해 필요합니다.",
        what_to_check=(
            "SDS의 성상·물리적 상태",
            "제품 농도 또는 함량",
            "상온·상압에서 액체인지 여부 등 해당 특수조건",
        ),
        legal_basis="「유해화학물질의 규정수량에 관한 규정」 제3조 및 별표 2·별표 3의 해당 항목",
        decision_effect="특수조건이 확인되면 해당 조건에 맞는 규정수량 행으로 최대보유량을 비교합니다.",
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
        legal_basis="「유해화학물질의 규정수량에 관한 규정」 제3조제1호 및 별표 1",
        legal_hierarchy=(
            "적용 구조: 「유해화학물질의 규정수량에 관한 규정」 제3조",
            "유해성·위험성 그룹별 규정수량: 같은 규정 별표 1",
        ),
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
        legal_basis="해당 규정수량 별표의 물질명·범위·비고",
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
