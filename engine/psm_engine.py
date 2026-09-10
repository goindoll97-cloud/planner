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
# industry names are not auto-classified because that could create a false
# legal determination.
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

# Annex 13 rows whose legal identity is directly expressible using the ordinary
# product concentration field in the company intake workbook.
PRODUCT_CONCENTRATION_MIN = {
    22: 94.5,  # 질산
    24: 52.0,  # 과산화수소
    48: 10.0,  # 불산
    49: 20.0,  # 염산
    50: 20.0,  # 황산
    51: 20.0,  # 암모니아수
}

# These legal conditions are NOT the same as the generic product 함량(%).
# They are therefore held for an explicit follow-up rather than guessed.
SPECIAL_CONDITION_QUESTIONS = {
    23: "발연황산(8014-95-7)의 삼산화황 중량이 65% 이상 80% 미만인지 확인해 주세요.",
    42: "니트로셀룰로오스(9004-70-0)의 질소 함유량이 12.6% 이상인지 확인해 주세요.",
}

# Same CAS appears in both anhydrous and aqueous/concentration-defined rows.
ANHYDROUS_ITEMS = {12, 13}
AQUEOUS_COUNTERPART = {12: 48, 13: 49}


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
class PSMRatioLine:
    legal_item_no: int
    legal_substance: str
    source_rows: str
    cas_values: str
    manufacture_handling_kg: float
    storage_kg: float
    manufacture_handling_threshold_kg: float
    storage_threshold_kg: float
    manufacture_handling_ratio: float
    storage_ratio: float
    controlling_ratio: float
    controlling_basis: str
    quantity_basis: str


@dataclass
class PSMAssessment:
    status: str
    label: str
    hits: list[PSMHit] = field(default_factory=list)
    ratio_lines: list[PSMRatioLine] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    industry_code: str = ""
    industry_match: str = ""
    db_ready: bool = False
    r_value: float | None = None
    r_complete: bool = False


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


def _valid_pct(value: Any) -> float | None:
    pct = _number(value)
    if pct is None or pct <= 0 or pct > 100:
        return None
    return pct


def _load_db() -> pd.DataFrame:
    if not APPROVED_PSM_DB.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(APPROVED_PSM_DB)
    except Exception:
        return pd.DataFrame()
    required = {
        "item_no",
        "substance_name",
        "cas_list",
        "match_type",
        "manufacture_handling_threshold_kg",
        "storage_threshold_kg",
    }
    if not required.issubset(df.columns):
        return pd.DataFrame()
    for col in ["item_no", "manufacture_handling_threshold_kg", "storage_threshold_kg"]:
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


def _legal_condition(
    legal: dict[str, Any],
    company_pct: Any,
    product_name: str,
    cas: str,
) -> tuple[bool | None, float | None, str, str]:
    """Return (applicable, mass_factor, basis, question).

    Annex 13 note 6 states that regulatory quantity is based on 100% purity,
    except chemicals for which the table itself specifies a concentration. For
    ordinary exact-CAS rows we therefore use pure-substance-equivalent mass
    (product mass × concentration/100). For concentration-defined rows whose
    condition maps directly to the workbook's product 함량(%), the product mass
    is compared after the concentration condition is satisfied.

    Conditions such as SO3 content in fuming sulfuric acid and nitrogen content
    in nitrocellulose are not silently mapped to the generic product 함량 field.
    """
    item_no = int(float(legal.get("item_no")))
    legal_name = _clean(legal.get("substance_name"))
    pct = _valid_pct(company_pct)
    who = product_name or cas or f"별표13 제{item_no}호"

    if item_no in SPECIAL_CONDITION_QUESTIONS:
        return None, None, "별도 법정 성분조건 확인 필요", SPECIAL_CONDITION_QUESTIONS[item_no]

    if item_no in PRODUCT_CONCENTRATION_MIN:
        minimum = PRODUCT_CONCENTRATION_MIN[item_no]
        if pct is None:
            return (
                None,
                None,
                f"법정 농도조건 {minimum:g}% 이상",
                f"{who}: 별표 13 제{item_no}호({legal_name}) 판정을 위해 제품 함량(%)을 확인해 주세요.",
            )
        if pct < minimum:
            return False, None, f"함량 {pct:g}% < 법정기준 {minimum:g}%", ""
        return True, 1.0, f"함량 {pct:g}% ≥ 법정기준 {minimum:g}%: 제품질량 기준", ""

    if item_no in ANHYDROUS_ITEMS:
        if pct is None:
            return (
                None,
                None,
                "무수물 여부 확인 필요",
                f"{who}: 별표 13 제{item_no}호({legal_name})의 무수물 해당 여부와 함량(%)을 확인해 주세요.",
            )
        if pct < 100.0:
            # Aqueous counterpart (48/49) is evaluated separately for the same
            # CAS. Do not apply the anhydrous threshold to a stated dilute product.
            return False, None, f"함량 {pct:g}%: 무수물 행 자동적용 제외", ""
        return True, 1.0, "함량 100%: 무수물 행 적용", ""

    if pct is None:
        return (
            None,
            None,
            "순도 100% 환산을 위한 함량 필요",
            f"{who}: 별표 13 비고 제6호의 순도 100% 기준 환산을 위해 함량(%)을 확인해 주세요.",
        )

    return True, pct / 100.0, f"순도 100% 환산계수 {pct / 100.0:.4f} (함량 {pct:g}%)", ""


def _property_questions() -> list[str]:
    return [
        (
            "별표 13 제1호 '인화성 가스'에 해당하는 물질이 있습니까? "
            "인화한계 최저한도 13% 이하 또는 최고·최저한도 차 12% 이상이고, "
            "표준압력에서 20℃에 가스 상태인 물질인지 확인해 주세요. 해당한다면 하루 최대 제조·취급량과 저장량도 필요합니다."
        ),
        (
            "별표 13 제2호 '인화성 액체'에 해당하는 물질이 있습니까? "
            "표준압력에서 인화점 60℃ 이하이거나 고온·고압 공정조건에서 화재·폭발위험이 있는 가연성 물질인지 확인해 주세요. "
            "해당한다면 하루 최대 제조·취급량과 저장량도 필요합니다."
        ),
    ]


def _aggregate_ratio_lines(
    contributions: list[dict[str, Any]],
) -> list[PSMRatioLine]:
    """Aggregate company rows by Annex 13 legal item and calculate C/T.

    Annex 13 note 7 uses the largest manufacture/handling-or-storage C/T for
    each hazardous substance, then sums those per-substance ratios when two or
    more substances are present. Multiple company inventory rows mapped to the
    same legal item are summed before the ratio is calculated so split inventory
    lines cannot create a false negative.
    """
    grouped: dict[int, dict[str, Any]] = {}
    for row in contributions:
        item_no = int(row["item_no"])
        g = grouped.setdefault(
            item_no,
            {
                "legal_substance": row["legal_substance"],
                "source_rows": set(),
                "cas_values": set(),
                "mfg": 0.0,
                "storage": 0.0,
                "mfg_seen": False,
                "storage_seen": False,
                "mfg_threshold": float(row["mfg_threshold"]),
                "storage_threshold": float(row["storage_threshold"]),
                "quantity_basis": set(),
            },
        )
        g["source_rows"].add(int(row["company_row"]))
        g["cas_values"].add(str(row["cas"]))
        g["quantity_basis"].add(str(row["quantity_basis"]))
        if row.get("mfg_kg") is not None:
            g["mfg"] += float(row["mfg_kg"])
            g["mfg_seen"] = True
        if row.get("storage_kg") is not None:
            g["storage"] += float(row["storage_kg"])
            g["storage_seen"] = True

    out: list[PSMRatioLine] = []
    for item_no in sorted(grouped):
        g = grouped[item_no]
        mfg_t = float(g["mfg_threshold"])
        storage_t = float(g["storage_threshold"])
        mfg_ratio = (float(g["mfg"]) / mfg_t) if g["mfg_seen"] and mfg_t > 0 else 0.0
        storage_ratio = (float(g["storage"]) / storage_t) if g["storage_seen"] and storage_t > 0 else 0.0
        if mfg_ratio >= storage_ratio:
            controlling = mfg_ratio
            controlling_basis = "제조·취급"
        else:
            controlling = storage_ratio
            controlling_basis = "저장"
        out.append(
            PSMRatioLine(
                legal_item_no=item_no,
                legal_substance=str(g["legal_substance"]),
                source_rows=", ".join(str(v) for v in sorted(g["source_rows"])),
                cas_values=", ".join(sorted(g["cas_values"])),
                manufacture_handling_kg=round(float(g["mfg"]), 6),
                storage_kg=round(float(g["storage"]), 6),
                manufacture_handling_threshold_kg=mfg_t,
                storage_threshold_kg=storage_t,
                manufacture_handling_ratio=round(mfg_ratio, 8),
                storage_ratio=round(storage_ratio, 8),
                controlling_ratio=round(controlling, 8),
                controlling_basis=controlling_basis,
                quantity_basis=" / ".join(sorted(g["quantity_basis"])),
            )
        )
    return out


def calculate_r_value(lines: list[PSMRatioLine]) -> float:
    """Annex 13 note 7(b): R = sum of each hazardous substance's max C/T."""
    return float(sum(line.controlling_ratio for line in lines))


def _hit_from_line(line: PSMRatioLine) -> PSMHit:
    if line.controlling_basis == "저장":
        quantity = line.storage_kg
        threshold = line.storage_threshold_kg
        kind = "저장"
    else:
        quantity = line.manufacture_handling_kg
        threshold = line.manufacture_handling_threshold_kg
        kind = "제조·취급"
    return PSMHit(
        row_no=int(line.source_rows.split(",")[0].strip()),
        product_name="",
        cas=line.cas_values,
        legal_item_no=line.legal_item_no,
        legal_substance=line.legal_substance,
        quantity_kind=kind,
        quantity_kg=quantity,
        threshold_kg=threshold,
        ratio=line.controlling_ratio,
        basis="산업안전보건법 시행령 별표 13 비고 제7호(C/T 및 R 산정)",
    )


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
                "합성수지 및 기타 플라스틱물질 제조업은 별표 13 제1호 또는 제2호 해당 여부와 함께 대상업종 조건을 확인해야 합니다. 사업장에서 인화성 가스 또는 인화성 액체를 제조·취급·저장합니까?"
            )
        else:
            assessment.messages.append(f"PSM 대상업종 코드와 일치: {code} {assessment.industry_match}")

    lookup = _cas_lookup(db)
    contributions: list[dict[str, Any]] = []
    unsupported_mass_unit_rows: set[int] = set()
    missing_cas_rows: set[int] = set()
    quantity_missing_rows: set[int] = set()
    pending_questions: list[str] = []
    pending_condition_items: set[int] = set()

    for idx, row in intake.chemicals.iterrows():
        company_row = idx + 1
        cas = _clean(row.get("CAS No."))
        product = _clean(row.get("제품명"))
        if not CAS_RE.fullmatch(cas):
            if product:
                missing_cas_rows.add(company_row)
            continue

        legal_rows = lookup.get(cas, [])
        if not legal_rows:
            continue

        unit = row.get("수량 단위")
        unit_norm = _clean(unit).lower().replace(" ", "")
        raw_mfg = _number(row.get("최대 제조·사용량"))
        raw_storage = _number(row.get("최대 저장량"))
        if unit_norm not in {"kg", "ton", "t", "톤"}:
            if raw_mfg is not None or raw_storage is not None:
                unsupported_mass_unit_rows.add(company_row)
            continue
        if raw_mfg is None and raw_storage is None:
            quantity_missing_rows.add(company_row)
            continue

        company_pct = row.get("함량(%)")
        evaluated: list[tuple[dict[str, Any], bool | None, float | None, str, str]] = []
        for legal in legal_rows:
            applicable, factor, basis, question = _legal_condition(legal, company_pct, product, cas)
            evaluated.append((legal, applicable, factor, basis, question))

        # When the company explicitly states 100%, the anhydrous legal row takes
        # precedence over its aqueous counterpart for the same CAS. This avoids
        # double-counting one physical substance as two Annex 13 types.
        pct = _valid_pct(company_pct)
        anhydrous_applicable = {
            int(float(legal.get("item_no")))
            for legal, applicable, _, _, _ in evaluated
            if int(float(legal.get("item_no"))) in ANHYDROUS_ITEMS and applicable is True
        }

        for legal, applicable, factor, basis, question in evaluated:
            item_no = int(float(legal.get("item_no")))
            if item_no in AQUEOUS_COUNTERPART.values() and pct == 100.0:
                parent = 12 if item_no == 48 else 13 if item_no == 49 else None
                if parent in anhydrous_applicable:
                    continue
            if applicable is None:
                pending_condition_items.add(item_no)
                if question:
                    pending_questions.append(question)
                continue
            if applicable is False or factor is None:
                continue

            mfg_threshold = _number(legal.get("manufacture_handling_threshold_kg"))
            storage_threshold = _number(legal.get("storage_threshold_kg"))
            if not mfg_threshold or not storage_threshold:
                pending_condition_items.add(item_no)
                assessment.blockers.append(f"별표 13 제{item_no}호 규정량 DB 값 확인 필요")
                continue

            mfg_kg = _kg(row.get("최대 제조·사용량"), unit)
            storage_kg = _kg(row.get("최대 저장량"), unit)
            effective_mfg = None if mfg_kg is None else mfg_kg * factor
            effective_storage = None if storage_kg is None else storage_kg * factor
            contributions.append(
                {
                    "company_row": company_row,
                    "cas": cas,
                    "item_no": item_no,
                    "legal_substance": _clean(legal.get("substance_name")),
                    "mfg_kg": effective_mfg,
                    "storage_kg": effective_storage,
                    "mfg_threshold": mfg_threshold,
                    "storage_threshold": storage_threshold,
                    "quantity_basis": basis,
                }
            )

    if missing_cas_rows:
        rows = ", ".join(map(str, sorted(missing_cas_rows)))
        assessment.questions.append(f"화학물질 목록 {rows}행의 CAS No.를 확인해 주세요. CAS가 없으면 별표 13 정확 매칭을 완료할 수 없습니다.")
        assessment.blockers.append(f"CAS 미확인 행: {rows}")

    if unsupported_mass_unit_rows:
        rows = ", ".join(map(str, sorted(unsupported_mass_unit_rows)))
        assessment.questions.append(
            f"화학물질 목록 {rows}행은 질량 단위가 아닙니다. PSM 규정량(kg) 비교를 위해 최대 질량(kg/ton) 또는 밀도정보가 필요합니다."
        )
        assessment.blockers.append(f"질량 환산 필요 행: {rows}")

    if quantity_missing_rows:
        rows = ", ".join(map(str, sorted(quantity_missing_rows)))
        assessment.questions.append(
            f"화학물질 목록 {rows}행은 별표 13 매칭 물질이지만 최대 제조·사용량과 최대 저장량이 모두 비어 있습니다. 하루 최대 제조·취급 또는 저장량을 확인해 주세요."
        )
        assessment.blockers.append(f"PSM 일일 최대량 미확인 행: {rows}")

    assessment.questions.extend(pending_questions)
    if pending_condition_items:
        assessment.blockers.append(
            "법정 농도·성분조건 미확인 항목: " + ", ".join(str(v) for v in sorted(pending_condition_items))
        )

    assessment.ratio_lines = _aggregate_ratio_lines(contributions)
    assessment.r_value = round(calculate_r_value(assessment.ratio_lines), 8)

    # Items 1 and 2 are property-defined and have no exact CAS identity. They
    # remain an explicit dynamic question unless a positive target result has
    # already been established by industry or the checked R value.
    property_unresolved = bool(
        "match_type" in db.columns and db["match_type"].astype(str).eq("PROPERTY").any()
    )

    industry_positive = bool(assessment.industry_match and code != "20202")
    r_positive = bool(assessment.r_value is not None and assessment.r_value >= 1.0)
    individual_positive_lines = [line for line in assessment.ratio_lines if line.controlling_ratio >= 1.0]
    assessment.hits = [_hit_from_line(line) for line in individual_positive_lines]

    unresolved_nonproperty = bool(assessment.blockers)
    assessment.r_complete = not unresolved_nonproperty and not property_unresolved

    if assessment.ratio_lines:
        assessment.messages.append(
            f"별표 13 비고 제7호에 따른 현재 확인 범위의 규정량 대비 합산값 R = {assessment.r_value:.4f}. "
            "각 물질은 제조·취급 C/T와 저장 C/T 중 큰 값을 사용해 합산했습니다."
        )
        if len(assessment.ratio_lines) > 1:
            assessment.messages.append(
                "동일 별표 13 항목이 회사 목록 여러 행에 나뉜 경우 해당 항목의 입력량을 먼저 합산한 뒤 C/T를 계산했습니다."
            )

    if industry_positive or r_positive:
        assessment.status = "APPLICABLE_CANDIDATE"
        assessment.label = "PSM 대상 후보"
        assessment.questions.extend(PSM_EXCLUSION_QUESTIONS)
        if r_positive:
            assessment.messages.append(
                "현재 확인된 별표 13 물질만으로 R이 1 이상이므로 규정량 기준의 PSM 대상 트리거가 확인되었습니다. "
                "제43조제2항 제외설비 등 최종 제외조건 확인 전에는 확정 '대상'으로 표시하지 않습니다."
            )
            assessment.questions.append(
                "별표 13 비고 제8호와 관련하여, R 산정에 포함된 가스가 '가스를 전문으로 저장·판매하는 시설 내의 가스'에 해당하는지 확인해 주세요. 해당 가스는 규정량 산정에서 제외될 수 있습니다."
            )
    elif code == "20202":
        assessment.status = "ADDITIONAL_INFO_REQUIRED"
        assessment.label = "PSM 대상업종 조건 확인 필요"
    else:
        if property_unresolved:
            assessment.questions.extend(_property_questions())
            assessment.blockers.append("별표 13 제1호 인화성 가스 / 제2호 인화성 액체 여부 미확인")
        assessment.r_complete = not assessment.blockers
        if assessment.questions or assessment.blockers:
            assessment.status = "ADDITIONAL_INFO_REQUIRED"
            assessment.label = "PSM 추가정보 필요"
        else:
            assessment.status = "NO_TRIGGER_IN_CHECKED_SCOPE"
            assessment.label = "확인 범위 내 PSM 기준 초과 없음"
            assessment.messages.append(
                "현재 승인된 별표 13 DB와 입력자료에서 R < 1이고 추가 미확인 조건이 없습니다. 다만 대상업종·제외설비 등 전체 법정조건 검증 범위 내에서 최종 비대상 여부를 확정해야 합니다."
            )

    assessment.questions = list(dict.fromkeys(q for q in assessment.questions if q))
    assessment.blockers = list(dict.fromkeys(b for b in assessment.blockers if b))
    return assessment
