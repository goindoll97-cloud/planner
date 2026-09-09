from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .inventory import IntakeData
from .regulatory_db import load_cap_rules, load_psm_rules, normalize_cas


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_FILE = PROJECT_ROOT / "data" / "regulatory" / "regulatory_manifest.json"


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _float(value: object) -> float | None:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _mass_to_kg(value: object, unit: object) -> float | None:
    amount = _float(value)
    if amount is None:
        return None
    u = _clean(unit).lower()
    if u == "kg":
        return amount
    if u == "ton":
        return amount * 1000.0
    return None


def _mass_to_ton(value: object, unit: object) -> float | None:
    kg = _mass_to_kg(value, unit)
    return None if kg is None else kg / 1000.0


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_FILE.exists():
        return {}
    try:
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _verified(key: str) -> bool:
    row = _load_manifest().get(key, {})
    return bool(isinstance(row, dict) and row.get("verified_complete") is True)


@dataclass
class MaterialDecision:
    row_no: int
    cas: str
    product_name: str
    cap_decision: str = ""
    cap_basis: str = ""
    psm_decision: str = ""
    psm_basis: str = ""
    questions: list[str] = field(default_factory=list)


@dataclass
class RuleEngineResult:
    cap_result: str
    psm_result: str
    materials: list[MaterialDecision]
    questions: list[str]
    messages: list[str]


def _cap_material(row: pd.Series, row_no: int, cap_rules: pd.DataFrame) -> MaterialDecision:
    cas = normalize_cas(row.get("CAS No."))
    item = MaterialDecision(row_no=row_no, cas=cas, product_name=_clean(row.get("제품명")))
    if not cas:
        item.cap_decision = "판정보류"
        item.questions.append(f"화학물질 {row_no}: CAS No.를 확인해 주세요.")
        return item

    matched = cap_rules[cap_rules["cas"].eq(cas)] if not cap_rules.empty else pd.DataFrame()
    if matched.empty:
        item.cap_decision = "규정DB 미매칭"
        return item

    simultaneous = _mass_to_ton(row.get("최대 동시보유량(알면 입력)"), row.get("수량 단위"))
    if simultaneous is None:
        item.cap_decision = "판정보류"
        item.questions.append(
            f"화학물질 {row_no} ({cas}): 화사계 판정을 위해 최대 동시보유량을 kg 또는 ton으로 확인해 주세요."
        )
        return item

    # More than one approved row for the same CAS is handled conservatively:
    # the most stringent available quantity triggers the classification.
    lowers = [v for v in matched["lower_ton"].tolist() if pd.notna(v)]
    uppers = [v for v in matched["upper_ton"].tolist() if pd.notna(v)]
    if not lowers or not uppers:
        item.cap_decision = "판정보류"
        item.questions.append(f"화학물질 {row_no} ({cas}): 승인 규정수량 DB의 상·하위 수량을 확인해 주세요.")
        return item

    lower = min(float(v) for v in lowers)
    upper = min(float(v) for v in uppers)
    if simultaneous >= upper:
        item.cap_decision = "1군 트리거 후보"
    elif simultaneous >= lower:
        item.cap_decision = "2군 트리거 후보"
    else:
        item.cap_decision = "하위 규정수량 미만 후보"
    item.cap_basis = f"최대 동시보유량 {simultaneous:g} ton / 하위 {lower:g} ton / 상위 {upper:g} ton"
    return item


def _psm_material(row: pd.Series, row_no: int, psm_rules: pd.DataFrame, item: MaterialDecision) -> MaterialDecision:
    cas = item.cas
    if not cas:
        item.psm_decision = "판정보류"
        if not any("CAS No." in q for q in item.questions):
            item.questions.append(f"화학물질 {row_no}: CAS No.를 확인해 주세요.")
        return item

    matched = psm_rules[psm_rules["cas"].eq(cas)] if not psm_rules.empty else pd.DataFrame()
    if matched.empty:
        item.psm_decision = "별표13 CAS 미매칭"
        return item

    manufacture_kg = _mass_to_kg(row.get("최대 제조·사용량"), row.get("수량 단위"))
    storage_kg = _mass_to_kg(row.get("최대 저장량"), row.get("수량 단위"))
    if manufacture_kg is None and storage_kg is None:
        item.psm_decision = "판정보류"
        item.questions.append(
            f"화학물질 {row_no} ({cas}): PSM 판정을 위해 최대 제조·사용량 또는 최대 저장량을 kg/ton으로 확인해 주세요."
        )
        return item

    triggered = False
    bases: list[str] = []
    for _, rule in matched.iterrows():
        m_limit = rule.get("manufacture_use_kg")
        s_limit = rule.get("storage_kg")
        if pd.notna(m_limit) and manufacture_kg is not None:
            bases.append(f"제조·사용 {manufacture_kg:g}/{float(m_limit):g} kg")
            if manufacture_kg >= float(m_limit):
                triggered = True
        if pd.notna(s_limit) and storage_kg is not None:
            bases.append(f"저장 {storage_kg:g}/{float(s_limit):g} kg")
            if storage_kg >= float(s_limit):
                triggered = True
    item.psm_decision = "별표13 규정량 이상 후보" if triggered else "별표13 규정량 미만 후보"
    item.psm_basis = "; ".join(bases)
    return item


def run_rule_engine(intake: IntakeData) -> RuleEngineResult:
    cap_rules = load_cap_rules()
    psm_rules = load_psm_rules()
    cap_verified = _verified("CAP_QTY")
    psm_verified = _verified("PSM_APP13")

    materials: list[MaterialDecision] = []
    questions: list[str] = []
    messages: list[str] = []

    for idx, row in intake.chemicals.iterrows():
        item = _cap_material(row, idx + 1, cap_rules)
        item = _psm_material(row, idx + 1, psm_rules, item)
        materials.append(item)
        questions.extend(item.questions)

    cap_values = [m.cap_decision for m in materials]
    psm_values = [m.psm_decision for m in materials]

    if not cap_verified:
        cap_result = "판정보류"
        messages.append("화사계 규정수량 DB가 공식 최신 별표 전체 검증 완료 상태가 아닙니다.")
    elif any(v == "판정보류" for v in cap_values):
        cap_result = "판정보류"
    elif any(v == "1군 트리거 후보" for v in cap_values):
        cap_result = "1군 후보"
    elif any(v == "2군 트리거 후보" for v in cap_values):
        cap_result = "2군 후보"
    elif any(v == "규정DB 미매칭" for v in cap_values):
        cap_result = "판정보류"
        messages.append("화사계 승인 DB에 매칭되지 않는 CAS가 있어 전체 비대상을 확정하지 않습니다.")
    else:
        cap_result = "하위 규정수량 미만 후보"

    if not psm_verified:
        psm_result = "판정보류"
        messages.append("PSM 별표 13 DB가 공식 최신 별표 전체 검증 완료 상태가 아닙니다.")
    elif any(v == "판정보류" for v in psm_values):
        psm_result = "판정보류"
    elif any(v == "별표13 규정량 이상 후보" for v in psm_values):
        psm_result = "PSM 대상 후보"
    else:
        # This only addresses Appendix 13 exact-CAS material triggers. Target
        # industries, generic categories, concentration notes and excluded
        # facilities are deliberately handled in later rules.
        psm_result = "추가조건 확인 필요"
        messages.append("별표 13 CAS 비교 외에 대상업종·일반분류·농도조건·제외설비 확인이 남아 있습니다.")

    # Deduplicate while preserving order.
    questions = list(dict.fromkeys(questions))
    return RuleEngineResult(
        cap_result=cap_result,
        psm_result=psm_result,
        materials=materials,
        questions=questions,
        messages=messages,
    )


def material_result_frame(result: RuleEngineResult) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "행": m.row_no,
            "제품명": m.product_name,
            "CAS No.": m.cas,
            "화사계 물질판정": m.cap_decision,
            "화사계 근거": m.cap_basis,
            "PSM 물질판정": m.psm_decision,
            "PSM 근거": m.psm_basis,
        }
        for m in result.materials
    ])
