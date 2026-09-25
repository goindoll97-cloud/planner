from __future__ import annotations

"""시행규칙 제29조에 따른 별지 제2호 후속조치 후보 제안.

법적 결정을 추정하지 않는다. 사용자가 확인한 사실만으로 변경허가/변경신고
후보를 제안하고, 결정조건이 빠져 있으면 HOLD 성격의 확인사항을 반환한다.
"""

from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Any, Mapping


RULE_PATH = Path(__file__).resolve().parents[2] / "data" / "stage2" / "cap_rule29_followup_rules.json"

PERMIT = "영업허가"
DECLARATION = "영업신고"
UNKNOWN = "미확인"

CHANGE_PERMISSION = "㈑ 변경허가"
CHANGE_REPORT = "㈐ 변경신고"


@dataclass(frozen=True)
class FollowUpSuggestion:
    actions: tuple[str, ...] = ()
    legal_basis: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return bool(self.actions) and not self.questions


def _yes(value: Any) -> bool:
    return str(value or "").strip().lower() in {"y", "yes", "예", "해당", "true", "1"}


def _no(value: Any) -> bool:
    return str(value or "").strip().lower() in {"n", "no", "아니오", "미해당", "false", "0", "없음"}


def _choice(value: Any) -> str:
    return str(value or "").strip()


def load_rule29_rules() -> dict[str, Any]:
    return json.loads(RULE_PATH.read_text(encoding="utf-8"))


def suggest_rule29_followup(facts: Mapping[str, Any]) -> FollowUpSuggestion:
    """Return fail-closed Rule 29 follow-up candidates.

    Expected fact keys are deliberately plain and UI-friendly:
    business_status: 영업허가 / 영업신고 / 미확인
    name_representative_office_changed, site_address_changed,
    pilot_production_60d, facility_or_material_changed,
    transport_vehicle_changed, technical_personnel_changed,
    storage_or_transport_capacity_increased, max_holding_sum_increased,
    cumulative_capacity_increase_50pct, cumulative_holding_increase_50pct,
    chemical_added_or_amount_increased, transport_business,
    quantity_band: 하위 미만 / 최하위 이상·하위 미만 / 하위 이상
    scenario_quantity_or_more, overall_impact_expanded,
    cap_change_submission_required
    """
    status = _choice(facts.get("business_status"))
    if status not in {PERMIT, DECLARATION}:
        return FollowUpSuggestion(
            questions=("유해화학물질 영업 상태를 '영업허가' 또는 '영업신고'로 확인해 주세요.",),
            legal_basis=("「화학물질관리법 시행규칙」 제29조제1항",),
        )

    actions: list[str] = []
    bases: list[str] = []
    reasons: list[str] = []
    questions: list[str] = []

    def add(action: str, clause: str, reason: str) -> None:
        if action not in actions:
            actions.append(action)
        if clause not in bases:
            bases.append(clause)
        if reason not in reasons:
            reasons.append(reason)

    if status == PERMIT:
        if _yes(facts.get("name_representative_office_changed")):
            add(CHANGE_REPORT, "시행규칙 제29조제1항제2호가목", "사업장 명칭·대표자 또는 사무실 소재지 변경")

        if _yes(facts.get("site_address_changed")):
            add(CHANGE_PERMISSION, "시행규칙 제29조제1항제1호마목", "사업장 소재지 변경(사무실 소재지 제외)")

        if _yes(facts.get("pilot_production_60d")):
            if _yes(facts.get("scenario_quantity_or_more")):
                add(CHANGE_REPORT, "시행규칙 제29조제1항제2호나목", "60일 이내 시범생산 물질 일시변경 + 사고시나리오 규정량 이상")
            elif not _no(facts.get("scenario_quantity_or_more")):
                questions.append("시범생산 변경 후 취급량이 사고시나리오 규정량 이상인지 확인해 주세요.")

        if _yes(facts.get("facility_or_material_changed")):
            cap_required = facts.get("cap_change_submission_required")
            expanded = facts.get("overall_impact_expanded")
            scenario = facts.get("scenario_quantity_or_more")
            if _yes(cap_required):
                add(CHANGE_PERMISSION, "시행규칙 제29조제1항제1호라목", "시설 신설·증설·위치 변경 또는 취급물질 변경 + 변경된 화사계 제출 필요")
            elif _no(cap_required):
                if _no(expanded) and _yes(scenario):
                    add(CHANGE_REPORT, "시행규칙 제29조제1항제2호다목", "시설/물질 변경 + 총괄영향범위 미확대 + 사고시나리오 규정량 이상")
                else:
                    if not (_yes(expanded) or _no(expanded)):
                        questions.append("시설/물질 변경으로 총괄영향범위가 확대되는지 확인해 주세요.")
                    if not (_yes(scenario) or _no(scenario)):
                        questions.append("변경 후 취급량이 사고시나리오 규정량 이상인지 확인해 주세요.")
            else:
                questions.append("시설/물질 변경으로 변경된 화학사고예방관리계획서 제출이 필요한지 확인해 주세요.")

        if _yes(facts.get("transport_vehicle_changed")):
            if _yes(facts.get("cumulative_capacity_increase_50pct")):
                add(CHANGE_PERMISSION, "시행규칙 제29조제1항제1호가목", "운반시설 용량 누적 증가량 50% 이상")
            elif _no(facts.get("cumulative_capacity_increase_50pct")):
                add(CHANGE_REPORT, "시행규칙 제29조제1항제2호라목", "운반차량 종류 변경·대수 또는 용량 증가")
            else:
                questions.append("운반시설 용량 증가가 허가/변경허가 후 누적 50% 이상인지 확인해 주세요.")

        if _yes(facts.get("technical_personnel_changed")):
            add(CHANGE_REPORT, "시행규칙 제29조제1항제2호마목", "법 제28조제2항에 따른 기술인력 변경")

        if _yes(facts.get("storage_or_transport_capacity_increased")):
            if _yes(facts.get("cumulative_capacity_increase_50pct")):
                add(CHANGE_PERMISSION, "시행규칙 제29조제1항제1호가목", "보관·저장시설 총용량 또는 운반시설 용량 누적 증가량 50% 이상")
            elif not _no(facts.get("cumulative_capacity_increase_50pct")):
                questions.append("보관·저장/운반시설 용량 증가가 허가 또는 변경허가 후 누적 50% 이상인지 확인해 주세요.")

        if _yes(facts.get("max_holding_sum_increased")):
            if _yes(facts.get("cumulative_holding_increase_50pct")):
                add(CHANGE_PERMISSION, "시행규칙 제29조제1항제1호나목", "유해화학물질별 최대보유량 합계 누적 증가량 50% 이상")
            elif not _no(facts.get("cumulative_holding_increase_50pct")):
                questions.append("최대보유량 합계 증가가 허가 또는 변경허가 후 누적 50% 이상인지 확인해 주세요.")

        if _yes(facts.get("chemical_added_or_amount_increased")) and not _yes(facts.get("transport_business")):
            band = _choice(facts.get("quantity_band"))
            if band == "하위 이상":
                add(CHANGE_PERMISSION, "시행규칙 제29조제1항제1호다목", "유해화학물질 추가·증가 후 취급량이 하위 규정수량 이상")
            elif band == "최하위 이상·하위 미만":
                add(CHANGE_REPORT, "시행규칙 제29조제1항제2호바목", "유해화학물질 추가·증가 후 취급량이 최하위 이상 하위 미만")
            elif band not in {"하위 미만", "최하위 미만"}:
                questions.append("추가·증가한 유해화학물질의 취급량 규정수량 구간을 확인해 주세요.")

    else:  # 영업신고
        if _yes(facts.get("name_representative_office_changed")) or _yes(facts.get("site_address_changed")):
            add(CHANGE_REPORT, "시행규칙 제29조제1항제3호가목", "영업신고 사업장의 명칭·대표자·소재지 변경")

        if _yes(facts.get("storage_or_transport_capacity_increased")):
            if _yes(facts.get("cumulative_capacity_increase_50pct")):
                add(CHANGE_REPORT, "시행규칙 제29조제1항제3호나목", "보관·저장시설 총용량 누적 증가량 50% 이상")
            elif not _no(facts.get("cumulative_capacity_increase_50pct")):
                questions.append("보관·저장시설 총용량 증가가 신고/변경신고 후 누적 50% 이상인지 확인해 주세요.")

        if _yes(facts.get("max_holding_sum_increased")):
            if _yes(facts.get("cumulative_holding_increase_50pct")):
                add(CHANGE_REPORT, "시행규칙 제29조제1항제3호다목", "최대보유량 합계 누적 증가량 50% 이상")
            elif not _no(facts.get("cumulative_holding_increase_50pct")):
                questions.append("최대보유량 합계 증가가 신고/변경신고 후 누적 50% 이상인지 확인해 주세요.")

        if _yes(facts.get("chemical_added_or_amount_increased")):
            band = _choice(facts.get("quantity_band"))
            if band == "최하위 이상·하위 미만":
                add(CHANGE_REPORT, "시행규칙 제29조제1항제3호라목", "유해화학물질 추가·증가 후 최대보유량이 최하위 이상 하위 미만")
            elif band not in {"하위 미만", "최하위 미만"}:
                questions.append("추가·증가한 유해화학물질의 최대보유량 규정수량 구간을 확인해 주세요.")

    return FollowUpSuggestion(
        actions=tuple(actions),
        legal_basis=tuple(bases),
        reasons=tuple(reasons),
        questions=tuple(dict.fromkeys(questions)),
    )
