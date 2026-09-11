from __future__ import annotations

"""Final CAP applicability/group decision after quantity screening.

The engine returns a final write/non-write result only when quantity evidence,
statutory exemptions, and (for an upper-quantity site result) major-facility
facts are resolved. Missing decisive facts remain HOLD.

Legal structure:
- 화학물질관리법 제23조제1항
- 화학물질관리법 시행규칙 제19조제2항 및 제8항
- 화학사고예방관리계획서 작성 등에 관한 규정(2026-7) 제2조, 제4조, 제6조, 제9조
"""

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class CAPExemptionOption:
    key: str
    label: str
    plain_language: str
    legal_basis: str


EXEMPTIONS: tuple[CAPExemptionOption, ...] = (
    CAPExemptionOption(
        "LAW_LAB", "연구실 안전환경 조성에 관한 법률상 연구실",
        "해당 유해화학물질 취급시설이 법에서 정한 연구실에 해당하는 경우입니다.",
        "「화학물질관리법」 제23조제1항제1호",
    ),
    CAPExemptionOption(
        "LAW_SCHOOL", "학교안전사고 예방 및 보상에 관한 법률상 학교",
        "해당 유해화학물질 취급시설이 법에서 정한 학교에 설치·운영되는 경우입니다.",
        "「화학물질관리법」 제23조제1항제2호",
    ),
    CAPExemptionOption(
        "RULE_TRANSPORT_STORAGE_METHOD", "시행규칙 별표 1 제5호라목 단서 방식의 운반·보관시설",
        "시행규칙에서 별도로 정한 운반·보관 방법에 해당하는 시설입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제1호",
    ),
    CAPExemptionOption(
        "RULE_VEHICLE", "유해화학물질 운반 차량(상·하차 제외)",
        "운반 중인 차량 자체는 면제되지만 차량에 싣거나 내리는 작업은 포함되지 않습니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제3호",
    ),
    CAPExemptionOption(
        "RULE_MILITARY", "군사기지·군사시설 내 유해화학물질 취급시설",
        "군사기지 및 군사시설 보호법에서 정한 군사기지·군사시설 내 취급시설입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제4호",
    ),
    CAPExemptionOption(
        "RULE_MEDICAL", "의료기관 내 유해화학물질 취급시설",
        "의료법에서 정한 의료기관 내 유해화학물질 취급시설입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제5호",
    ),
    CAPExemptionOption(
        "RULE_PORT", "승인된 자체안전관리계획이 있는 항만 포장·용기 보관시설",
        "항만시설에서 포장·용기에 담긴 유해화학물질을 보관하고 법정 자체안전관리계획 승인을 받은 경우입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제6호",
    ),
    CAPExemptionOption(
        "RULE_RAIL", "철도시설의 포장·용기 임시보관시설(지체 없이 역외 반출)",
        "철도시설에서 포장·용기에 담긴 유해화학물질을 보관하고 법정 요건에 따라 지체 없이 역외 반출하는 경우입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제7호",
    ),
    CAPExemptionOption(
        "RULE_PESTICIDE", "등록된 농약 판매업자의 보관·저장시설",
        "농약관리법에 따라 판매업을 등록한 자가 사용하는 유해화학물질 보관·저장시설입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제8호",
    ),
    CAPExemptionOption(
        "RULE_AIRPORT", "공항 보호구역 내 항공운송사업자·공항운영자 취급시설",
        "항공보안법상 보호구역에서 법정 항공운송사업자 또는 공항운영자가 설치·운영하는 시설입니다.",
        "「화학물질관리법 시행규칙」 제19조제2항제9호",
    ),
    CAPExemptionOption(
        "NOTICE_CONSUMER_PACKAGE", "소비자 판매용 포장제품 보관·진열시설",
        "유해화학물질 포함 제품을 포장된 상태로 소비자에게 판매하기 위해 보관·진열하는 시설입니다.",
        "「화학사고예방관리계획서 작성 등에 관한 규정」(2026-7) 제9조제1호",
    ),
    CAPExemptionOption(
        "NOTICE_WASTE_TEMP", "폐기물 처리를 위한 유해화학물질 폐기물 임시보관시설",
        "폐기물 수집·운반·보관·재활용·처분을 위해 일시 보관하는 시설입니다.",
        "같은 고시 제9조제2호",
    ),
    CAPExemptionOption(
        "NOTICE_END_CONTROL", "공정 끝단의 대기·수질 오염물질 제거·감소 배출시설",
        "공정 마지막 단계의 끝단 배출시설입니다. 중화·제거용 유해화학물질 투입 저장·사용시설은 제외되지 않습니다.",
        "같은 고시 제9조제3호",
    ),
    CAPExemptionOption(
        "NOTICE_EMBEDDED", "기계·장치에 내장되어 정상 사용 중 유출·누출·비산 우려가 없는 경우",
        "유해화학물질이 기계·장치 내부에 내장되어 정상 사용 과정에서 밖으로 나오지 않는 경우입니다.",
        "같은 고시 제9조제4호가목",
    ),
    CAPExemptionOption(
        "NOTICE_SOLID_PRODUCT", "고체 기능성 제품에 함유되어 유출·누출·비산되지 않는 경우",
        "특정 기능을 발휘하는 고체 제품 속에 들어 있어 정상 취급 중 유출·누출·비산되지 않는 경우입니다.",
        "같은 고시 제9조제4호나목",
    ),
    CAPExemptionOption(
        "NOTICE_MAINT_PAINT", "사업장 시설 유지보수용 도료·염료 구매·취급",
        "사업장 시설 유지보수를 위해 도료 또는 염료를 구매·취급하는 경우입니다.",
        "같은 고시 제9조제4호다목",
    ),
    CAPExemptionOption(
        "NOTICE_SOLID_LEAD", "분말·미립자 비산 우려가 없는 고체 납(잉곳 등)",
        "CAS 7439-92-1 납을 고체 상태로 취급하면서 분말·미립자가 체류하거나 날릴 우려가 없는 경우입니다.",
        "같은 고시 제9조제4호라목",
    ),
    CAPExemptionOption(
        "NOTICE_NATURAL", "화학적으로 변형·추출·정제하지 않은 법정 자연상태 물질",
        "법정 자연상태 물질을 화학적으로 변형·추출·정제하지 않은 경우입니다.",
        "같은 고시 제9조제4호마목",
    ),
    CAPExemptionOption(
        "NOTICE_GAS_STATION", "고정 주유설비로 휘발유·등유·경유를 판매하는 주유소",
        "석유사업법령상 주유소가 고정 주유설비로 휘발유·등유·경유를 판매하는 시설입니다.",
        "같은 고시 제9조제5호",
    ),
)


@dataclass
class CAPFinalDecision:
    status: str
    label: str
    group: str = ""
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    legal_basis: list[str] = field(default_factory=list)
    next_question: str = ""

    @property
    def is_final(self) -> bool:
        return self.status in {"REQUIRED_GROUP_1", "REQUIRED_GROUP_2", "NOT_REQUIRED"}


def exemption_options() -> tuple[CAPExemptionOption, ...]:
    return EXEMPTIONS


def exemption_by_key(key: str) -> CAPExemptionOption | None:
    return next((item for item in EXEMPTIONS if item.key == str(key or "")), None)


def normalize_quantity_evidence(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize APP1/2/3 comparison rows to UPPER/LOWER/BELOW evidence.

    BELOW must be checked before LOWER because the internal status
    ``BELOW_LOWER`` contains the substring ``LOWER``.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        band_raw = str(row.get("quantity_band") or row.get("status") or "")
        band = band_raw.upper()
        if "BELOW" in band or "하위 규정수량 미만" in band_raw:
            level = "BELOW"
        elif "UPPER" in band or "상위 규정수량 이상" in band_raw:
            level = "UPPER"
        elif "LOWER" in band or "하위 이상" in band_raw:
            level = "LOWER"
        else:
            continue
        out.append({**row, "decision_level": level})
    return out


def assess_cap_final(
    quantity_rows: Iterable[dict[str, Any]],
    *,
    unresolved_blockers: Iterable[str] = (),
    exemption_answer: str = "UNANSWERED",
    exemption_key: str = "",
    exemption_all_relevant_confirmed: bool = False,
    major_facility_answer: str = "UNANSWERED",
) -> CAPFinalDecision:
    """Return the final CAP decision using fail-closed legal facts.

    exemption_answer: NONE / EXEMPT / PARTIAL / UNKNOWN / UNANSWERED
    major_facility_answer: YES / NO / UNKNOWN / UNANSWERED
    """
    blockers = list(dict.fromkeys(str(v) for v in unresolved_blockers if str(v).strip()))
    rows = normalize_quantity_evidence(quantity_rows)
    if blockers:
        return CAPFinalDecision(
            "HOLD", "판정보류 — 먼저 확인할 정보가 있습니다", blockers=blockers,
            next_question="표시된 미확인 물질·최대보유량 정보를 먼저 확인해 주세요.",
        )

    upper = [row for row in rows if row["decision_level"] == "UPPER"]
    lower = [row for row in rows if row["decision_level"] == "LOWER"]
    if not upper and not lower:
        return CAPFinalDecision(
            "NOT_REQUIRED", "작성 비대상 — 확인된 물질 모두 하위 규정수량 미만",
            reasons=["현재 확인이 끝난 유해화학물질 중 하위 규정수량 이상인 물질이 없습니다."],
            legal_basis=["「화학물질관리법 시행규칙」 제19조제2항제2호"],
        )

    answer = str(exemption_answer or "UNANSWERED").upper()
    if answer in {"UNANSWERED", "UNKNOWN"}:
        return CAPFinalDecision(
            "HOLD", "면제조건 확인 필요",
            next_question="규정수량 이상 판단에 영향을 주는 관련 취급시설이 법정 작성 면제시설에 해당하는지 확인해 주세요.",
            legal_basis=["「화학물질관리법」 제23조제1항", "같은 법 시행규칙 제19조제2항", "화학사고예방관리계획서 작성 등에 관한 규정 제9조"],
        )
    if answer == "PARTIAL":
        return CAPFinalDecision(
            "HOLD", "판정보류 — 일부 시설만 면제될 수 있습니다",
            blockers=["면제시설을 제외한 뒤 남는 취급시설의 물질별 최대보유량을 다시 산정해야 합니다."],
            next_question="면제시설을 제외한 비면제 취급시설 기준 최대보유량을 확인해 주세요.",
        )
    if answer == "EXEMPT":
        option = exemption_by_key(exemption_key)
        if option is None:
            return CAPFinalDecision("HOLD", "면제유형 확인 필요", blockers=["선택한 면제유형을 법적 기준과 연결하지 못했습니다."])
        if not exemption_all_relevant_confirmed:
            return CAPFinalDecision(
                "HOLD", "면제범위 확인 필요",
                blockers=["선택한 면제유형이 규정수량 판정에 영향을 주는 관련 취급시설 전체에 적용되는지 확인되지 않았습니다."],
                next_question="관련 취급시설 전체가 선택한 면제유형에 해당하는지 확인해 주세요.",
                legal_basis=[option.legal_basis],
            )
        return CAPFinalDecision(
            "NOT_REQUIRED", "작성 비대상 — 법정 면제시설",
            reasons=[option.label, option.plain_language], legal_basis=[option.legal_basis],
        )

    # NONE: no legal exemption applies.
    if upper:
        major = str(major_facility_answer or "UNANSWERED").upper()
        if major == "YES":
            return CAPFinalDecision(
                "REQUIRED_GROUP_1", "작성 필요 — 1군 사업장", group="1군",
                reasons=[
                    "하나 이상의 물질이 사업장 최대보유량 기준 상위 규정수량 이상입니다.",
                    "상위 규정수량 이상의 유해화학물질을 취급하는 주요취급시설을 운영합니다.",
                ],
                legal_basis=[
                    "「화학물질관리법 시행규칙」 제19조제8항",
                    "「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제1항제12의1, 제4조 및 제6조",
                ],
            )
        if major == "NO":
            return CAPFinalDecision(
                "HOLD", "판정보류 — 상위기준이나 주요취급시설이 확인되지 않았습니다",
                blockers=["사업장 최대보유량은 여러 시설의 합일 수 있으므로 상위 규정수량 이상 결과만으로 개별 주요취급시설 존재를 자동 확정할 수 없습니다."],
                next_question="상위 규정수량 해당 물질의 시설별 취급량을 확인해 주요취급시설 여부를 검토해 주세요.",
                legal_basis=["「화학물질관리법 시행규칙」 제19조제8항", "「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제1항제12의1"],
            )
        return CAPFinalDecision(
            "HOLD", "주요취급시설 여부 확인 필요",
            next_question="상위 규정수량 이상인 물질을 하나의 취급시설에서 상위 규정수량 이상 취급하는 시설이 있는지 확인해 주세요.",
            legal_basis=["「화학물질관리법 시행규칙」 제19조제8항"],
        )

    return CAPFinalDecision(
        "REQUIRED_GROUP_2", "작성 필요 — 2군 사업장", group="2군",
        reasons=["면제조건에 해당하지 않으며 하나 이상의 유해화학물질 최대보유량이 하위 규정수량 이상 상위 규정수량 미만입니다."],
        legal_basis=["「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제1항제12의2, 제4조 및 제6조"],
    )
