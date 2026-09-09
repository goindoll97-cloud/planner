from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .inventory import IntakeData


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVED_PSM_DB = PROJECT_ROOT / "data" / "regulatory" / "approved" / "psm_annex13.csv"

# Current 산업안전보건법 시행령 제43조제1항 target-industry codes.
# Exact KSIC codes are used only when the company supplies a code; free-text
# industry names are not auto-classified because that could create a false legal determination.
PSM_TARGET_INDUSTRIES = {
    "19210": "원유 정제처리업",
    "19229": "기타 석유정제물 재처리업",
    "20111": "석유화학계 기초화학물질 제조업",
    "20202": "합성수지 및 기타 플라스틱물질 제조업",
    "20311": "질소 화합물, 질소·인산 및 칼리질 화학비료 제조업 중 질소질 비료 제조",
    "20312": "복합비료 및 기타 화학비료 제조업 중 복합비료 제조",
    "20321": "화학 살균·살충제 및 농업용 약제 제조업 중 농약 원제 제조",
    "20494": "화약 및 불꽃제품 제조업",
}

PSM_EXCLUSION_QUESTIONS = [
    "해당 설비가 원자력 설비에 해당합니까?",
    "해당 설비가 군사시설에 해당합니까?",
    "해당 설비가 사업장 내 직접 사용을 위한 난방용 연료의 저장·사용설비에 해당합니까?",
    "해당 설비가 도매·소매시설에 해당합니까?",
    "해당 설비가 차량 등의 운송설비에 해당합니까?",
    "해당 설비가 「액화석유가스의 안전관리 및 사업법」에 따른 액화석유가스 충전·저장시설에 해당합니까?",
    "해당 설비가 「도시가스사업법」에 따른 가스공급시설에 해당합니까?",
    "그 밖에 고용노동부장관이 피해 정도가 크지 않다고 인정하여 고시한 제외설비에 해당합니까?",
]

CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")
PCT_RE = re.compile(r"(?:중량\s*)?(\d+(?:\.\d+)?)\s*%\s*이상")


@dataclass
class PSMHit:
    row_no: int
    product_name: str
    cas: str
    legal_item_no: int
    legal_substance: str
    quantity_kind: str
    quantity_kg: float
    threshold_kg: float
    ratio: float
    basis: str


@dataclass
class PSMAssessment:
    status: str
    label: str
    hits: list[PSMHit] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    industry_code: str = ""
    industry_match: str = ""
    db_ready: bool = False


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _number(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group()) if match else None


def _kg(value: Any, unit: Any) -> float | None:
    amount = _number(value)
    if amount is None:
        return None
    norm = _clean(unit).lower().replace(" ", "")
    if norm == "kg":
        return amount
    if norm in {"ton", "t", "톤"}:
        return amount * 1000.0
    return None


def _load_db() -> pd.DataFrame:
    if not APPROVED_PSM_DB.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(APPROVED_PSM_DB)
    except Exception:
        return pd.DataFrame()
    for col in ["item_no", "manufacture_handling_threshold_kg", "storage_threshold_kg"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _cas_lookup(df: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = {}
    if df.empty:
        return lookup
    for _, row in df.iterrows():
        for cas in str(row.get("cas_list", "")).split("|"):
            cas = cas.strip()
            if CAS_RE.fullmatch(cas):
                lookup.setdefault(cas, []).append(row.to_dict())
    return lookup


def _concentration_allows(legal_name: str, company_pct: Any) -> tuple[bool | None, str]:
    match = PCT_RE.search(legal_name)
    if not match:
        return True, ""
    required = float(match.group(1))
    actual = _number(company_pct)
    if actual is None:
        return None, f"{legal_name}: 법정 함량기준 {required:g}% 이상 여부 확인 필요"
    return actual >= required, f"함량 {actual:g}% / 법정기준 {required:g}% 이상"


def assess_psm(intake: IntakeData) -> PSMAssessment:
    db = _load_db()
    if db.empty:
        return PSMAssessment(
            status="DB_NOT_READY",
            label="PSM 규정량 DB 승인 필요",
            messages=["산업안전보건법 시행령 별표 13의 구조화 후보를 검토·승인한 뒤 PSM 수량판정을 활성화합니다."],
            db_ready=False,
        )

    assessment = PSMAssessment(status="REVIEW", label="추가 확인 필요", db_ready=True)
    code = _clean(intake.business.get("한국표준산업분류(KSIC) 코드"))
    code = re.sub(r"\D", "", code)
    assessment.industry_code = code
    if code in PSM_TARGET_INDUSTRIES:
        assessment.industry_match = PSM_TARGET_INDUSTRIES[code]
        if code == "20202":
            assessment.questions.append(
                "합성수지 및 기타 플라스틱물질 제조업은 시행령 별표 13 제1호 또는 제2호 해당 여부를 확인해야 합니다. 사업장에서 인화성 가스 또는 인화성 액체를 제조·취급·저장합니까?"
            )
        else:
            assessment.messages.append(f"PSM 대상업종 코드와 일치: {code} {assessment.industry_match}")

    lookup = _cas_lookup(db)
    unresolved_property = False
    unsupported_mass_unit_rows: list[int] = []
    concentration_pending: list[str] = []

    for idx, row in intake.chemicals.iterrows():
        company_row = idx + 1
        cas = _clean(row.get("CAS No."))
        product = _clean(row.get("제품명"))
        if not CAS_RE.fullmatch(cas):
            continue
        legal_rows = lookup.get(cas, [])
        for legal in legal_rows:
            allowed, conc_note = _concentration_allows(str(legal.get("substance_name", "")), row.get("함량(%)"))
            if allowed is None:
                concentration_pending.append(f"{product or cas}: {conc_note}")
                continue
            if not allowed:
                continue

            unit = row.get("수량 단위")
            mfg_kg = _kg(row.get("최대 제조·사용량"), unit)
            storage_kg = _kg(row.get("최대 저장량"), unit)
            if _clean(unit).lower() not in {"kg", "ton", "t", "톤"}:
                if _number(row.get("최대 제조·사용량")) is not None or _number(row.get("최대 저장량")) is not None:
                    unsupported_mass_unit_rows.append(company_row)
                continue

            mfg_threshold = _number(legal.get("manufacture_handling_threshold_kg"))
            storage_threshold = _number(legal.get("storage_threshold_kg"))
            item_no = int(float(legal.get("item_no")))
            legal_name = _clean(legal.get("substance_name"))
            if mfg_kg is not None and mfg_threshold and mfg_kg >= mfg_threshold:
                assessment.hits.append(
                    PSMHit(
                        row_no=company_row,
                        product_name=product,
                        cas=cas,
                        legal_item_no=item_no,
                        legal_substance=legal_name,
                        quantity_kind="제조·취급",
                        quantity_kg=mfg_kg,
                        threshold_kg=mfg_threshold,
                        ratio=mfg_kg / mfg_threshold,
                        basis="산업안전보건법 시행령 제43조제1항 및 별표 13",
                    )
                )
            if storage_kg is not None and storage_threshold and storage_kg >= storage_threshold:
                assessment.hits.append(
                    PSMHit(
                        row_no=company_row,
                        product_name=product,
                        cas=cas,
                        legal_item_no=item_no,
                        legal_substance=legal_name,
                        quantity_kind="저장",
                        quantity_kg=storage_kg,
                        threshold_kg=storage_threshold,
                        ratio=storage_kg / storage_threshold,
                        basis="산업안전보건법 시행령 제43조제1항 및 별표 13",
                    )
                )

    # Annex 13 items 1-2 are property-defined, not CAS-defined; without an
    # explicit hazard-class input the engine must not declare a negative result.
    if not db.empty and "match_type" in db.columns and db["match_type"].astype(str).eq("PROPERTY").any():
        unresolved_property = True
        assessment.questions.append(
            "CAS만으로는 별표 13 제1호 인화성 가스 및 제2호 인화성 액체 여부를 확정할 수 없습니다. 해당되는 물질이 사업장에 있는지 확인해 주세요."
        )

    if unsupported_mass_unit_rows:
        rows = ", ".join(map(str, sorted(set(unsupported_mass_unit_rows))))
        assessment.questions.append(
            f"화학물질 목록 {rows}행은 L 또는 m3 등 질량이 아닌 단위입니다. PSM 규정량(kg) 비교를 위해 최대 질량(kg/ton) 또는 밀도정보가 필요합니다."
        )
    assessment.questions.extend(concentration_pending)

    industry_positive = bool(assessment.industry_match and code != "20202")
    quantity_positive = bool(assessment.hits)
    if industry_positive or quantity_positive:
        assessment.status = "APPLICABLE_CANDIDATE"
        assessment.label = "PSM 대상 후보"
        assessment.questions.extend(PSM_EXCLUSION_QUESTIONS)
        assessment.messages.append(
            "시행령 제43조제2항의 제외설비 해당 여부를 확인하기 전에는 최종 '대상'으로 확정하지 않습니다."
        )
    elif code == "20202":
        assessment.status = "ADDITIONAL_INFO_REQUIRED"
        assessment.label = "PSM 대상업종 조건 확인 필요"
    elif assessment.questions:
        assessment.status = "ADDITIONAL_INFO_REQUIRED"
        assessment.label = "PSM 추가정보 필요"
    else:
        # This is a scoped preliminary result: exact CAS/approved DB and supplied
        # quantities found no trigger. It is intentionally not labelled final non-applicable.
        assessment.status = "NO_TRIGGER_IN_CHECKED_SCOPE"
        assessment.label = "확인 범위 내 PSM 기준 초과 없음"
        assessment.messages.append(
            "현재 승인된 별표 13 CAS 규칙과 입력 수량 범위에서는 기준 초과가 확인되지 않았습니다. 인화성 가스·액체 및 제외/업종 조건까지 확인해야 최종 비대상을 판단할 수 있습니다."
        )

    # Deduplicate dynamic questions while preserving order.
    assessment.questions = list(dict.fromkeys(q for q in assessment.questions if q))
    return assessment
