from __future__ import annotations

"""Final company-facing CAP applicability/group decision.

This module intentionally runs *after* the material/quantity engines.  It does
not infer missing legal facts.  Quantity screening, statutory exemptions and
1군/2군 classification are kept separate so the UI can explain exactly which
fact is still missing.

Current legal structure encoded here (verified 2026-09):
- 화학물질관리법 제23조제1항
- 같은 법 시행규칙 제19조제2항 및 제8항
- 화학사고예방관리계획서 작성 등에 관한 규정 제2조, 제4조, 제6조, 제9조
  (화학물질안전원고시 제2026-7호, 시행 2026-04-22)
"""

from dataclasses import dataclass, field
from typing import Iterable


# Quantity states accepted from Appendix 1/2/3 comparison stages.
Q_UPPER = "UPPER_CANDIDATE"
Q_LOWER = "LOWER_CANDIDATE"
Q_BELOW = "BELOW_LOWER"
Q_NOT_APP1 = "NOT_APP1"
Q_HOLD = "HOLD"
Q_DB_NOT_READY = "DB_NOT_READY"


@dataclass(frozen=True)
class CAPExemptionOption:
    code: str
    label: str
    plain_language: str
    legal_basis: str


# §19(2)2 (all relevant substances below lower regulatory quantity) is not a
# question: the rule engine applies it automatically from verified quantities.
CAP_EXEMPTION_OPTIONS: tuple[CAPExemptionOption, ...] = (
    CAPExemptionOption(
        "NONE",
        "아래 면제유형에 해당하지 않음",
        "작성 검토대상인 유해화학물질 취급시설이 아래 법정 면제유형에 해당하지 않는 경우입니다.",
        "-",
    ),
    CAPExemptionOption(
        "LAW_RESEARCH_LAB",
        "연구실안전법상 연구실",
        "「연구실 안전환경 조성에 관한 법률」의 연구실에 해당하는 취급시설입니다.",
        "「화학물질관리법」 제23조제1항제1호",
    ),
    CAPExemptionOption(
        "LAW_SCHOOL",
        "학교안전법상 학교",
        "「학교안전사고 예방 및 보상에 관한 법률」의 학교에 해당하는 취급시설입니다.",
        "「화학물질관리법」 제23조제1항제2호",
    ),
    CAPExemptionOption(
        "RULE19_2_1_SPECIAL_TRANSPORT_STORAGE",
        "시행규칙 별표 1 제5호라목 단서 방식의 운반·보관시설",
        "시행규칙이 별도로 정한 운반·보관 방식에 해당하는 시설입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제1호",
    ),
    CAPExemptionOption(
        "RULE19_2_3_TRANSPORT_VEHICLE",
        "유해화학물질 운반 차량(상·하차 제외)",
        "유해화학물질을 운반하는 차량 자체입니다. 차량에 싣거나 내리는 시설·행위는 이 면제에 포함되지 않습니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제3호",
    ),
    CAPExemptionOption(
        "RULE19_2_4_MILITARY",
        "군사기지·군사시설 내 취급시설",
        "군사기지 및 군사시설 보호법상 군사기지 또는 군사시설 안의 유해화학물질 취급시설입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제4호",
    ),
    CAPExemptionOption(
        "RULE19_2_5_MEDICAL",
        "의료기관 내 취급시설",
        "의료법상 의료기관 안의 유해화학물질 취급시설입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제5호",
    ),
    CAPExemptionOption(
        "RULE19_2_6_PORT",
        "승인된 자체안전관리계획이 있는 항만 용기·포장 보관시설",
        "항만시설에서 유해화학물질이 담긴 용기·포장을 보관하고, 선박 입출항 관련 법률에 따른 자체안전관리계획 승인을 받은 경우입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제6호",
    ),
    CAPExemptionOption(
        "RULE19_2_7_RAIL",
        "철도시설 내 용기·포장 보관시설(지체 없이 역외 반출)",
        "철도시설에서 유해화학물질이 담긴 용기·포장을 보관하되 위험물철도운송규칙에 따라 지체 없이 역외 반출하는 경우입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제7호",
    ),
    CAPExemptionOption(
        "RULE19_2_8_PESTICIDE_RETAIL",
        "등록 농약판매업자의 유해화학물질 보관·저장시설",
        "농약관리법에 따라 판매업을 등록한 자가 사용하는 유해화학물질 보관·저장시설입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제8호",
    ),
    CAPExemptionOption(
        "RULE19_2_9_AIRPORT",
        "공항 보호구역 내 항공운송사업자·공항운영자 취급시설",
        "항공보안법상 보호구역에서 법정 항공운송사업자 또는 공항운영자가 설치·운영하는 취급시설입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제9호",
    ),
    # §19(2)10 -> current delegated notice §9
    CAPExemptionOption(
        "NOTICE9_1_CONSUMER_DISPLAY",
        "소비자 판매용 포장제품 보관·진열시설",
        "유해화학물질 포함 제품을 포장된 상태로 소비자에게 판매하기 위해 보관·진열하는 시설입니다.",
        "시행규칙 제19조제2항제10호 및 「화학사고예방관리계획서 작성 등에 관한 규정」 제9조제1호",
    ),
    CAPExemptionOption(
        "NOTICE9_2_WASTE_TEMP",
        "유해화학물질 폐기물 처리를 위한 임시보관시설",
        "폐기물관리법령에 따른 수집·운반·보관·재활용·처분을 위해 임시 보관하는 시설입니다.",
        "시행규칙 제19조제2항제10호 및 같은 고시 제9조제2호",
    ),
    CAPExemptionOption(
        "NOTICE9_3_END_OF_PIPE",
        "공정 끝단의 대기·수질 오염물질 제거·감소 배출시설",
        "공정 마지막 단계의 오염물질 제거·감소 시설입니다. 다만, 처리를 위해 유해화학물질을 투입하는 저장·사용시설은 제외되지 않습니다.",
        "시행규칙 제19조제2항제10호 및 같은 고시 제9조제3호",
    ),
    CAPExemptionOption(
        "NOTICE9_4A_EMBEDDED_NO_RELEASE",
        "기계·장치에 내장되어 정상 사용 중 유출·누출·비산되지 않는 경우",
        "유해화학물질이 기계·장치 내부에 내장되어 정상 사용과정에서 외부로 유출·누출·비산되지 않는 경우입니다.",
        "시행규칙 제19조제2항제10호 및 같은 고시 제9조제4호가목",
    ),
    CAPExemptionOption(
        "NOTICE9_4B_SOLID_FUNCTIONAL_PRODUCT",
        "고체 기능성 제품에 함유되어 유출·누출·비산되지 않는 경우",
        "특정 기능을 발휘하는 고체 제품에 유해화학물질이 함유되어 있으나 유출·누출·비산되지 않는 경우입니다.",
        "시행규칙 제19조제2항제10호 및 같은 고시 제9조제4호나목",
    ),
    CAPExemptionOption(
        "NOTICE9_4C_MAINTENANCE_PAINT_DYE",
        "사업장 시설 유지보수용 도료·염료 구매·취급",
        "사업장 시설의 유지보수를 위해 도료 또는 염료를 구매·취급하는 경우입니다.",
        "시행규칙 제19조제2항제10호 및 같은 고시 제9조제4호다목",
    ),
    CAPExemptionOption(
        "NOTICE9_4D_SOLID_LEAD",
        "분말·미립자 비산 우려가 없는 고체 납(잉곳 등)",
        "고체 상태의 납을 취급하고 분말·미립자가 체류하거나 날릴 우려가 없는 경우입니다.",
        "시행규칙 제19조제2항제10호 및 같은 고시 제9조제4호라목",
    ),
    CAPExemptionOption(
        "NOTICE9_4E_NATURAL_UNCHANGED",
        "자연 상태 물질을 화학적으로 변형·추출·정제하지 않은 경우",
        "관련 등록·신고 면제대상에 해당하는 자연 상태 물질을 화학적으로 변형, 추출, 정제하지 않은 경우입니다.",
        "시행규칙 제19조제2항제10호 및 같은 고시 제9조제4호마목",
    ),
    CAPExemptionOption(
        "NOTICE9_5_GAS_STATION",
        "고정 주유설비로 휘발유·등유·경유를 판매하는 주유소",
        "석유사업법령상 주유소가 고정된 주유설비로 휘발유·등유·경유를 판매하는 시설입니다.",
        "시행규칙 제19조제2항제10호 및 같은 고시 제9조제5호",
    ),
)

EXEMPTION_MAP = {option.code: option for option in CAP_EXEMPTION_OPTIONS}


@dataclass
class CAPFinalDecision:
    status: str
    label: str
    requires_plan: bool | None
    group: str | None = None
    blockers: list[str] = field(default_factory=list)
    legal_basis: list[str] = field(default_factory=list)
    next_action: str = ""
    exemption_code: str = ""


def exemption_options() -> tuple[CAPExemptionOption, ...]:
    return CAP_EXEMPTION_OPTIONS


def decide_cap_final(
    quantity_statuses: Iterable[str],
    *,
    all_quantity_facts_resolved: bool,
    exemption_code: str = "UNKNOWN",
    all_relevant_facilities_covered_by_exemption: bool | None = None,
    major_facility_answer: str = "UNKNOWN",
) -> CAPFinalDecision:
    """Return final write/non-write result without guessing missing facts.

    `quantity_statuses` should contain one status for every relevant material
    after APP3 -> APP2 -> APP1 priority and maximum-holding comparison.

    `major_facility_answer` is only used when an upper-quantity material exists:
    YES / NO / UNKNOWN.  A site-wide upper quantity does not by itself prove
    that one individual facility handles the upper regulatory quantity.
    """
    statuses = [str(v or "").strip() for v in quantity_statuses]
    unresolved = {Q_HOLD, Q_DB_NOT_READY, "", "NO_RESULT"}
    if not all_quantity_facts_resolved or any(v in unresolved for v in statuses):
        return CAPFinalDecision(
            status="HOLD",
            label="판정보류 — 규정수량 판정에 필요한 정보가 남아 있습니다",
            requires_plan=None,
            blockers=["물질별 규정수량 또는 최대보유량 확인이 모두 끝나야 작성 여부를 확정할 수 있습니다."],
            legal_basis=["「화학물질관리법」 제23조제1항", "「유해화학물질의 규정수량에 관한 규정」"],
            next_action="화면에 표시된 미확인 물질·수량 정보만 먼저 확인하세요.",
        )

    any_upper = any(v == Q_UPPER for v in statuses)
    any_lower = any(v == Q_LOWER for v in statuses)

    # Automatic quantity exemption: no relevant chemical reaches lower quantity.
    if not any_upper and not any_lower:
        return CAPFinalDecision(
            status="NOT_REQUIRED_QUANTITY",
            label="작성 불필요 — 확인된 유해화학물질이 모두 하위 규정수량 미만",
            requires_plan=False,
            legal_basis=["「화학물질관리법 시행규칙」 제19조제2항제2호"],
            next_action="수량·취급조건이 변경되면 다시 사전진단하세요.",
        )

    code = str(exemption_code or "UNKNOWN").strip()
    if code in {"", "UNKNOWN"}:
        return CAPFinalDecision(
            status="HOLD_EXEMPTION",
            label="판정보류 — 법정 작성면제 여부 확인 필요",
            requires_plan=None,
            blockers=["규정수량 기준은 충족했으므로 법정 작성면제 시설에 해당하는지 확인해야 합니다."],
            legal_basis=["「화학물질관리법」 제23조제1항", "같은 법 시행규칙 제19조제2항"],
            next_action="화면에 제시된 면제유형 중 작성 검토대상 시설 전체에 적용되는 항목이 있는지 확인하세요.",
        )

    if code != "NONE":
        option = EXEMPTION_MAP.get(code)
        if option is None:
            return CAPFinalDecision(
                status="HOLD_EXEMPTION",
                label="판정보류 — 선택한 면제유형 확인 필요",
                requires_plan=None,
                blockers=["현재 승인된 면제유형 목록과 연결되지 않는 값입니다."],
            )
        if all_relevant_facilities_covered_by_exemption is not True:
            return CAPFinalDecision(
                status="HOLD_EXEMPTION_SCOPE",
                label="판정보류 — 면제유형의 적용범위 확인 필요",
                requires_plan=None,
                blockers=["일부 시설만 면제유형에 해당한다면 사업장 전체를 비작성으로 확정할 수 없습니다."],
                legal_basis=[option.legal_basis],
                next_action="작성 검토대상 유해화학물질 취급시설 전체가 선택한 면제유형에 해당하는지 확인하세요.",
                exemption_code=code,
            )
        return CAPFinalDecision(
            status="NOT_REQUIRED_EXEMPT",
            label=f"작성 불필요 — 법정 작성면제 시설 ({option.label})",
            requires_plan=False,
            legal_basis=[option.legal_basis],
            next_action="면제사유를 입증할 수 있는 내부 자료를 보관하고 시설·취급조건이 바뀌면 다시 판정하세요.",
            exemption_code=code,
        )

    # No exemption. Lower-only site is a 2군 site.
    if not any_upper and any_lower:
        return CAPFinalDecision(
            status="REQUIRED_2",
            label="작성 필요 — 화학사고예방관리계획서 2군",
            requires_plan=True,
            group="2군",
            legal_basis=[
                "「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제1항제12의2호",
                "같은 규정 제4조 및 제6조",
            ],
            next_action="2군 작성항목에 필요한 자료만 다음 단계에서 수집하세요.",
        )

    # Upper site quantity: 1군 additionally requires operation of a major facility.
    major = str(major_facility_answer or "UNKNOWN").strip().upper()
    if any_upper and major == "YES":
        return CAPFinalDecision(
            status="REQUIRED_1",
            label="작성 필요 — 화학사고예방관리계획서 1군",
            requires_plan=True,
            group="1군",
            legal_basis=[
                "「화학물질관리법 시행규칙」 제19조제8항",
                "「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제1항제12의1호",
                "같은 규정 제4조 및 제6조",
            ],
            next_action="1군 작성항목에 필요한 자료를 다음 단계에서 수집하세요.",
        )

    # The plan is still required because the lower-quantity exemption no longer
    # applies, but current 1군 wording requires a major facility.  Never force a
    # 2군 classification when site maximum is already >= upper.
    return CAPFinalDecision(
        status="REQUIRED_GROUP_HOLD",
        label="작성 필요 — 작성수준(1군 여부) 추가 확인 필요",
        requires_plan=True,
        group=None,
        blockers=[
            "사업장 최대보유량은 상위 규정수량 이상이지만, 1군 판단에 필요한 '주요취급시설' 여부가 확인되지 않았습니다."
            if major == "UNKNOWN"
            else "사업장 최대보유량은 상위 규정수량 이상인데 주요취급시설은 없다고 확인되어, 현행 1군·2군 정의상 작성수준을 임의로 지정하지 않습니다."
        ],
        legal_basis=[
            "「화학물질관리법 시행규칙」 제19조제8항",
            "「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제1항제12의1호·제12의2호",
        ],
        next_action="해당 물질을 취급하는 개별 시설 중 상위 규정수량 이상을 취급하는 시설이 있는지 시설별 취급량으로 확인하세요.",
    )
