from __future__ import annotations

"""Plain-language consulting guidance used by company-facing screens.

The rule engine decides applicability. This module only explains why a fact is
requested, what it means, what the company should check, and where the legal
basis lives.  If an upper rule delegates detail to a notice, guidance follows
the delegation to the verified current notice whenever possible.
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
        title="별표 13 비고 제7호의 합산한 값(R)이 무엇인가요?",
        plain_language=(
            "PSM 별표 13 대상물질의 실제 제조·취급량 또는 저장량을 각 물질의 법정 규정량과 비교해 만든 비율입니다. "
            "여러 대상물질이 있으면 법에서 정한 방식으로 비율을 합산합니다."
        ),
        why_needed="시행령 제43조제1항 및 별표 13의 유해·위험물질 규정량 기준 해당 여부를 확인하기 위해 필요합니다.",
        what_to_check=("하루 최대 제조·취급량", "최대 저장량", "제품 함량 또는 순도"),
        example="별표 13 비고 제7호의 합산한 값(R)이 1.20이면 규정량 기준값 1을 초과한 것입니다. 다만 시행령 제43조제2항의 제외설비 여부도 함께 확인해야 제출 대상 여부가 확정됩니다.",
        legal_basis="「산업안전보건법 시행령」 제43조 및 별표 13",
        legal_hierarchy=("상위 근거: 「산업안전보건법」 제44조", "세부 대상·규정량: 같은 법 시행령 제43조 및 별표 13"),
        decision_effect="합산한 값(R)이 1 이상이면 시행령 제43조제1항의 사업 종류 및 제2항 제외설비 등 나머지 법정요건을 확인합니다.",
    ),
    "PSM_EXCLUDED_FACILITY": ConsultingGuide(
        key="PSM_EXCLUDED_FACILITY",
        title="PSM 제외설비가 무엇인가요?",
        plain_language="시행령 제43조제1항의 제출 대상 기준에 해당하더라도 같은 조 제2항에서 공정안전보고서 제출 대상에서 제외하는 설비가 있습니다.",
        why_needed="시행령 제43조제1항 기준에 해당하더라도 제2항의 제외설비에 해당하면 제출 대상에서 제외되기 때문입니다.",
        what_to_check=(
            "원자력 설비", "군사시설", "사업장 내 직접 사용을 위한 난방용 연료의 저장·사용설비", "도매·소매시설",
            "차량 등의 운송설비", "LPG 충전·저장시설", "도시가스 공급시설", "비상발전기용 경유의 저장탱크 및 사용설비",
        ),
        example="비상발전기용 경유 저장탱크·사용설비는 시행령의 '그 밖에 고시하는 설비'를 현행 고시가 구체화한 항목입니다.",
        legal_basis="「산업안전보건법 시행령」 제43조제2항",
        legal_hierarchy=(
            "상위 규정: 시행령 제43조제2항제8호",
            "구체화 규정: 「공정안전보고서의 제출·심사·확인 및 이행상태평가 등에 관한 규정」 제2조의2",
        ),
        resolved_detail="현행 고용노동부고시 제2025-30호 제2조의2: 비상발전기용 경유의 저장탱크 및 사용설비",
        source_status="현행 공식 행정규칙 확인",
        decision_effect="선택한 제외유형이 실제 관련 공정·설비에 적용되는지 확인한 뒤 제외 여부를 판단합니다.",
    ),
    "PSM_SPECIAL_CONDITION": ConsultingGuide(
        key="PSM_SPECIAL_CONDITION",
        title="왜 물성이나 별도 성분조건을 추가로 확인하나요?",
        plain_language="PSM 별표 13에는 CAS 번호만 같다고 자동 적용할 수 없는 물성·성분조건 항목이 있습니다.",
        why_needed="CAS 일치만으로 법정 항목을 잘못 적용하거나 제외하는 것을 막기 위해 필요합니다.",
        what_to_check=("SDS의 물리적·화학적 특성", "실제 성분함량·순도", "공정조건에서의 상태"),
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
        why_needed="화학사고예방관리계획서의 하위·상위 규정수량과 비교해 작성 필요성을 판단하기 위해 필요합니다.",
        what_to_check=("제조·사용시설", "저장탱크", "보관시설", "시설별 설계용량·밀도·보관량"),
        example="같은 물질이 저장탱크와 반응기에 동시에 존재할 수 있다면 관련 시설을 함께 고려합니다.",
        legal_basis="「유해화학물질의 규정수량에 관한 규정」 제2조제2호, 제4조 및 별표 4",
        legal_hierarchy=("정의: 같은 규정 제2조제2호", "시설유형별 계산방법: 같은 규정 제4조 및 별표 4"),
        decision_effect="최대보유량을 하위·상위 규정수량과 비교해 작성 필요성 및 작성수준 검토로 진행합니다.",
    ),
    "CAP_SPECIAL_CONDITION": ConsultingGuide(
        key="CAP_SPECIAL_CONDITION",
        title="왜 물질의 상태나 특수조건을 확인하나요?",
        plain_language="같은 물질이라도 농도나 상온·상압 상태 등에 따라 다른 규정수량을 적용하는 경우가 있습니다.",
        why_needed="잘못된 규정수량을 적용하지 않기 위해 필요합니다.",
        what_to_check=("SDS 성상·물리상태", "제품 농도·함량", "상온·상압 상태 등 해당 특수조건"),
        legal_basis="「유해화학물질의 규정수량에 관한 규정」 제3조 및 별표 2·별표 3",
        decision_effect="특수조건이 확인되면 맞는 규정수량 행으로 최대보유량을 비교합니다.",
    ),
    "KOSHA_CAS_SDS": ConsultingGuide(
        key="KOSHA_CAS_SDS",
        title="CAS 번호로 SDS 분류를 자동으로 확인할 수 있나요?",
        plain_language=(
            "가능한 경우 프로그램이 CAS 번호로 한국산업안전보건공단(KOSHA) 물질안전보건자료의 제2항 분류를 자동 조회하고 "
            "별표 1 후보를 먼저 연결합니다. 다만 KOSHA 자료는 MSDS 작성·검토용 참고자료이므로 회사가 실제 공급받은 제품 SDS와 일치 여부를 확인해야 합니다."
        ),
        why_needed="사용자가 SDS 분류를 처음부터 일일이 찾는 작업을 줄이되, 참고자료를 법적 제품 SDS로 오인하지 않기 위해 필요합니다.",
        what_to_check=("CAS 번호가 정확한지", "단일물질인지 혼합제품인지", "회사/공급자 SDS 제2항과 자동조회 결과가 일치하는지"),
        example="순물질 CAS가 정확히 매칭되면 자동 분류를 제시하고, 사용자는 회사 SDS와 일치 여부만 확인합니다. 혼합물·불일치·조회실패는 수동 SDS 확인으로 전환합니다.",
        legal_basis="한국산업안전보건공단 물질안전보건자료 조회 서비스(공공데이터포털 데이터셋 15157612) — 참고자료",
        source_status="공공데이터포털 KOSHA OpenAPI 연동",
        decision_effect="회사/제품 SDS와 일치가 확인된 자동분류만 별표 1 규정수량 판정에 사용합니다.",
    ),
    "CAP_APP1_SDS": ConsultingGuide(
        key="CAP_APP1_SDS",
        title="왜 SDS 유해성·위험성 분류를 확인하나요?",
        plain_language="물질별 직접목록으로 결론이 나지 않는 경우 별표 1은 SDS 제2항의 유해성·위험성 그룹을 기준으로 적용합니다.",
        why_needed="CAS 직접목록에서 찾지 못했다는 이유만으로 화학사고예방관리계획서 작성면제로 잘못 판단하는 것을 막기 위해 필요합니다.",
        what_to_check=("SDS 제2항 유해성·위험성", "급성독성 구분", "인화성 등 물리·화학적 위험성", "수생환경 유해성"),
        legal_basis="「유해화학물질의 규정수량에 관한 규정」 제3조제1호 및 별표 1",
        legal_hierarchy=("적용 구조: 같은 규정 제3조", "유해성·위험성 그룹별 규정수량: 같은 규정 별표 1"),
        decision_effect="SDS 분류가 확인되면 별표 1의 해당 그룹·구분과 규정수량을 연결합니다.",
    ),
    "CAP_EXEMPTIONS": ConsultingGuide(
        key="CAP_EXEMPTIONS",
        title="왜 작성면제 시설을 확인하나요?",
        plain_language=(
            "규정수량 이상이어도 법에서 화학사고예방관리계획서를 작성하지 않아도 된다고 정한 시설이 있습니다. "
            "프로그램은 현행 법·시행규칙과 시행규칙이 위임한 화학물질안전원고시의 면제시설까지 보여줍니다."
        ),
        why_needed="유해화학물질별 최대보유량과 규정수량 비교만으로 작성 필요 여부를 확정하면 법정 작성면제 시설을 놓칠 수 있기 때문입니다.",
        what_to_check=(
            "연구실안전법상 연구실 또는 학교안전법상 학교인지",
            "운반차량·군사시설·의료기관·항만·철도·농약판매·공항 등 시행규칙상 면제시설인지",
            "소비자 판매용 진열, 폐기물 임시보관, 공정 끝단 방지시설, 내장형·고체제품·유지보수 도료·고체 납·자연상태 물질·주유소 등 현행 고시상 면제시설인지",
        ),
        legal_basis="「화학물질관리법」 제23조제1항, 같은 법 시행규칙 제19조제2항, 「화학사고예방관리계획서 작성 등에 관한 규정」 제9조",
        legal_hierarchy=(
            "법 제23조제1항제1호·제2호: 연구실·학교",
            "시행규칙 제19조제2항제1호~제10호: 세부 작성면제 시설",
            "시행규칙 제19조제2항제10호의 위임사항: 현행 화학물질안전원고시 제2026-7호 제9조",
        ),
        source_status="현행 법령·행정규칙 확인",
        decision_effect="작성 검토대상 시설 전체가 법정 면제범위에 포함되는 경우 비작성으로 판단합니다. 일부 시설만 해당하면 전체를 면제하지 않습니다.",
    ),
    "CAP_MAJOR_FACILITY": ConsultingGuide(
        key="CAP_MAJOR_FACILITY",
        title="주요취급시설이 무엇인가요?",
        plain_language=(
            "사업장 전체 최대보유량과 별도로, 하나의 사업장 내 취급시설이 어떤 유해화학물질을 상위 규정수량 이상 취급하면 그 시설을 '주요취급시설'이라고 합니다. "
            "사업장 전체 합계가 상위 규정수량 이상이라는 사실만으로 개별 주요취급시설 존재를 자동 확정하지 않습니다."
        ),
        why_needed="현행 1군 정의는 주요취급시설을 운영하면서 물질별 사업장 최대보유량도 상위 규정수량 이상인 경우이기 때문입니다.",
        what_to_check=("상위기준 물질이 들어 있는 개별 저장·제조·사용·보관시설", "각 시설별 최대 취급량", "해당 물질의 상위 규정수량"),
        example="사업장 전체에 1.6 ton이 있어도 두 시설에 0.8 ton씩 나뉘어 있다면, 개별 시설이 상위 규정수량 이상인지 별도로 확인해야 합니다.",
        legal_basis="「화학물질관리법 시행규칙」 제19조제8항",
        decision_effect="주요취급시설 운영이 확인되고 사업장 최대보유량도 상위 규정수량 이상이면 1군 판단으로 진행합니다.",
    ),
    "CAP_FINAL_GROUP": ConsultingGuide(
        key="CAP_FINAL_GROUP",
        title="1군·2군은 어떻게 정해지나요?",
        plain_language=(
            "1군은 주요취급시설을 운영하면서 어느 한 유해화학물질의 사업장 최대보유량이 상위 규정수량 이상인 사업장입니다. "
            "2군은 어느 한 물질의 최대보유량이 하위 규정수량 이상 상위 규정수량 미만인 사업장입니다."
        ),
        why_needed="작성해야 할 항목과 이후 의무 수준을 정하기 위해 필요합니다.",
        legal_basis="「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제1항제12의1호·제12의2호, 제4조 및 제6조",
        source_status="화학물질안전원고시 제2026-7호 현행본 확인",
        decision_effect="면제조건이 없고 수량조건이 충족되면 1군 또는 2군 작성으로 확정합니다. 1군 요건의 일부 사실이 불명확하면 작성 필요성은 유지하되 작성수준만 판정보류합니다.",
    ),
    "CAP_BROAD_SCOPE": ConsultingGuide(
        key="CAP_BROAD_SCOPE",
        title="왜 CAS 번호만으로 판단할 수 없는 경우가 있나요?",
        plain_language="일부 법정 항목은 하나의 CAS가 아니라 염류·화합물군·혼합물·반응생성물처럼 더 넓은 범위를 규제합니다.",
        why_needed="법적 물질범위에 실제 포함되는지 별도로 확인하기 위해 필요합니다.",
        what_to_check=("제품 SDS의 성분명·CAS", "염·화합물 형태", "혼합물·반응생성물 여부", "법정 포함·제외조건"),
        legal_basis="해당 규정수량 별표의 물질명·범위·비고",
        decision_effect="범위 포함 여부가 확인되기 전까지 판정보류합니다.",
    ),
    "DECISION_HOLD": ConsultingGuide(
        key="DECISION_HOLD",
        title="'판정보류'는 무슨 뜻인가요?",
        plain_language="현재 정보만으로 법령상 제출·작성 필요 여부를 안전하게 확정할 수 없다는 뜻입니다. 확인이 끝날 때까지 판정을 보류합니다.",
        why_needed="법적 판단에 필요한 사실을 프로그램이 추정하지 않도록 하기 위한 안전장치입니다.",
        what_to_check=("함량·순도", "최대보유량", "SDS 분류", "시설 유형·면제조건", "법령·승인 DB 최신상태"),
        decision_effect="표시된 미확인 항목만 추가 확인한 뒤 다시 판정합니다.",
    ),
}


def get_guide(key: str) -> ConsultingGuide | None:
    return GUIDES.get(str(key or "").strip())


def all_guides() -> tuple[ConsultingGuide, ...]:
    return tuple(GUIDES.values())
