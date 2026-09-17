from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
import re
from typing import Iterable

import pandas as pd


CHEM_SHEET = "02_화학물질목록"
BUSINESS_SHEET = "01_사업장기본정보"
DOCS_SHEET = "03_기존문서보유여부"
FACILITY_SHEET = "04_시설별최대보유량"
LEGACY_FACILITY_SHEET = "03_시설별최대보유량"
FINAL_CONDITIONS_SHEET = "05_최종판정조건"
PSM_NOTE8_SHEET = "06_공정안전보고서_비고8제외수량"
LEGACY_PSM_NOTE8_SHEET = "06_공정안전보고서_비고8제외수량"
LEGACY_PSM_NOTE8_SHEET = "06_PSM_비고8제외수량"
MIXTURE_COMPONENT_SHEET = "02A_혼합물구성성분"
MIXTURE_FLAG_COLUMN = "혼합물 여부"
MIXTURE_COMPONENT_COLUMNS = [
    "적용여부", "제품목록행번호", "제품명(확인용)", "구성성분명", "CAS No.",
    "함량(%)", "함량 최저(%)", "함량 최고(%)", "SDS 제3항 근거", "비고",
]
_MIXTURE_CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")

REQUIRED_CHEM_COLUMNS = ["제품명", "CAS No.", "함량(%)", "취급형태", "수량 단위"]
QUANTITY_COLUMNS = ["최대 제조·사용량", "최대 저장량", "최대 동시보유량(알면 입력)"]


@dataclass
class IntakeData:
    business: dict[str, object]
    chemicals: pd.DataFrame
    documents: dict[str, object]
    facilities: pd.DataFrame = field(default_factory=pd.DataFrame)
    final_conditions: dict[str, object] = field(default_factory=dict)
    psm_note8_exclusions: pd.DataFrame = field(default_factory=pd.DataFrame)
    source_fingerprint: str = ""
    # SDS Section-3 components of commercial mixtures listed in
    # 02_화학물질목록. One product row can have several component rows here,
    # linked by "제품목록행번호". See engine.cap_mixture for how these are
    # screened against CAP Appendix 3/2 per component.
    mixture_components: pd.DataFrame = field(default_factory=pd.DataFrame)

    def mixture_parent_rows(self) -> set[int]:
        """Product rows in ``chemicals`` that are commercial mixtures.

        A row counts as a mixture if it is flagged 'Y' in the chemicals
        sheet's MIXTURE_FLAG_COLUMN, or if it has at least one row in
        ``mixture_components`` — either alone is enough to route that row
        through mixture-aware screening/validation.
        """
        rows: set[int] = set()
        if not self.mixture_components.empty and "제품목록행번호" in self.mixture_components.columns:
            for value in self.mixture_components["제품목록행번호"].tolist():
                row_no = _mixture_int(value)
                if row_no and row_no > 0:
                    rows.add(row_no)
        if MIXTURE_FLAG_COLUMN in self.chemicals.columns:
            for row_no, value in enumerate(self.chemicals[MIXTURE_FLAG_COLUMN].tolist(), start=1):
                if _mixture_yes(value):
                    rows.add(row_no)
        return rows


def _clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _mixture_clean(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _mixture_num(value: object) -> float | None:
    text = _mixture_clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _mixture_int(value: object) -> int | None:
    number = _mixture_num(value)
    if number is None or int(number) != number:
        return None
    return int(number)


def _mixture_yes(value: object) -> bool:
    return _mixture_clean(value).lower().replace(" ", "") in {"y", "yes", "예", "해당", "혼합물", "1", "true"}


def _mixture_no(value: object) -> bool:
    return _mixture_clean(value).lower().replace(" ", "") in {"n", "no", "아니오", "아님", "단일물질", "0", "false", "해당없음"}


def _mixture_concentration_values(component: "pd.Series") -> tuple[list[float], str]:
    """Resolve a component's SDS Section-3 concentration.

    Returns either one exact percentage, or a (low, high) range when the SDS
    only gives a range. Screening/holding treats a range that straddles a
    legal threshold as HOLD rather than silently picking one boundary.
    """
    exact = _mixture_num(component.get("함량(%)"))
    if exact is not None:
        return ([exact] if 0 <= exact <= 100 else []), "exact"
    low = _mixture_num(component.get("함량 최저(%)"))
    high = _mixture_num(component.get("함량 최고(%)"))
    if low is None or high is None or low < 0 or high > 100 or low > high:
        return [], "invalid"
    if low == high:
        return [low], "exact"
    return [low, high], "range"


def _read_optional_mixture_components(xls: pd.ExcelFile) -> pd.DataFrame:
    if MIXTURE_COMPONENT_SHEET not in xls.sheet_names:
        return pd.DataFrame(columns=MIXTURE_COMPONENT_COLUMNS)
    try:
        frame = pd.read_excel(xls, sheet_name=MIXTURE_COMPONENT_SHEET, header=2).dropna(how="all").copy()
    except Exception:
        return pd.DataFrame(columns=MIXTURE_COMPONENT_COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=MIXTURE_COMPONENT_COLUMNS)
    if "적용여부" in frame.columns:
        status = frame["적용여부"].map(_mixture_clean)
        frame = frame[~status.isin(["해당없음", "미해당", "N", "n"])].copy()
    for col in MIXTURE_COMPONENT_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    value_cols = ["제품목록행번호", "구성성분명", "CAS No.", "함량(%)", "함량 최저(%)", "함량 최고(%)"]
    frame = frame[frame[value_cols].notna().any(axis=1)].copy()
    return frame[MIXTURE_COMPONENT_COLUMNS].reset_index(drop=True)


def _apply_mixture_component_summary(data: IntakeData) -> None:
    frame = data.mixture_components
    if frame.empty:
        return
    data.chemicals["혼합물 구성성분 요약"] = ""
    summaries: dict[int, list[str]] = {}
    for _, component in frame.iterrows():
        parent = _mixture_int(component.get("제품목록행번호"))
        if not parent or parent > len(data.chemicals):
            continue
        values, mode = _mixture_concentration_values(component)
        pct = ""
        if values:
            pct = f"{values[0]:g}%" if mode == "exact" else f"{values[0]:g}~{values[-1]:g}%"
        text = " / ".join(
            v for v in [_mixture_clean(component.get("구성성분명")), _mixture_clean(component.get("CAS No.")), pct] if v
        )
        if text:
            summaries.setdefault(parent, []).append(text)
    for parent, values in summaries.items():
        data.chemicals.at[parent - 1, "혼합물 구성성분 요약"] = "; ".join(values)


def _mixture_validation_issues(data: IntakeData) -> list[str]:
    issues: list[str] = []
    frame = data.mixture_components
    for parent in sorted(data.mixture_parent_rows()):
        if parent <= 0 or parent > len(data.chemicals):
            issues.append(f"혼합물 구성성분: 제품목록행번호 {parent}가 02_화학물질목록에 없습니다.")
            continue
        components = frame[frame["제품목록행번호"].map(_mixture_int).eq(parent)] if not frame.empty and "제품목록행번호" in frame.columns else frame.iloc[0:0]
        if components.empty:
            product = _mixture_clean(data.chemicals.iloc[parent - 1].get("제품명"))
            issues.append(f"혼합물 {parent}행({product or '제품'}): 02A_혼합물구성성분에 구성성분을 한 줄 이상 작성해 주세요.")

    seen: set[tuple[int, str]] = set()
    for idx, row in frame.iterrows():
        excel_row = idx + 4
        parent = _mixture_int(row.get("제품목록행번호"))
        if not parent or parent > len(data.chemicals):
            issues.append(f"02A_혼합물구성성분 {excel_row}행: 유효한 제품목록행번호가 필요합니다.")
            continue
        if MIXTURE_FLAG_COLUMN in data.chemicals.columns and _mixture_no(data.chemicals.iloc[parent - 1].get(MIXTURE_FLAG_COLUMN)):
            issues.append(f"02A_혼합물구성성분 {excel_row}행: 구성성분이 입력된 제품 {parent}행의 '혼합물 여부'를 Y로 확인해 주세요.")
        name = _mixture_clean(row.get("구성성분명"))
        cas = _mixture_clean(row.get("CAS No."))
        if not name:
            issues.append(f"02A_혼합물구성성분 {excel_row}행: 구성성분명이 필요합니다.")
        if not _MIXTURE_CAS_RE.fullmatch(cas):
            issues.append(f"02A_혼합물구성성분 {excel_row}행({name or '성분'}): CAS No.를 확인해 주세요.")
        if not _mixture_concentration_values(row)[0]:
            issues.append(f"02A_혼합물구성성분 {excel_row}행({name or cas}): 함량(%) 또는 유효한 함량 최저·최고 범위가 필요합니다.")
        if not _mixture_clean(row.get("SDS 제3항 근거")):
            issues.append(f"02A_혼합물구성성분 {excel_row}행({name or cas}): SDS 제3항 등 함량근거를 작성해 주세요.")
        key = (parent, cas)
        if cas and key in seen:
            issues.append(f"02A_혼합물구성성분 {excel_row}행: 제품 {parent}행에 동일 CAS {cas}가 중복 입력되었습니다.")
        if cas:
            seen.add(key)
    return list(dict.fromkeys(issues))


def _norm_answer(value: object) -> str:
    return _clean_text(value).replace(" ", "").lower()


def _read_optional_facilities(xls: pd.ExcelFile) -> pd.DataFrame:
    sheet_name = ""
    if FACILITY_SHEET in xls.sheet_names:
        sheet_name = FACILITY_SHEET
    elif LEGACY_FACILITY_SHEET in xls.sheet_names:
        sheet_name = LEGACY_FACILITY_SHEET
    if not sheet_name:
        return pd.DataFrame()
    try:
        frame = pd.read_excel(xls, sheet_name=sheet_name, header=2)
    except Exception:
        return pd.DataFrame()
    if frame.empty:
        return frame
    frame = frame.dropna(how="all").copy()
    if "적용여부" in frame.columns:
        status = frame["적용여부"].map(_clean_text)
        frame = frame[~status.isin(["해당없음", "미해당", "N", "n"])].copy()
    value_cols = [c for c in ["시설명", "시설유형", "직접확인 최대보유량", "설계용량", "보관계획도 최대량", "일일최대보관량"] if c in frame.columns]
    if value_cols:
        frame = frame[frame[value_cols].notna().any(axis=1) | frame.get("적용여부", pd.Series(index=frame.index, dtype=object)).map(_clean_text).eq("모름")].copy()
    frame.reset_index(drop=True, inplace=True)
    return frame


def _read_optional_final_conditions(xls: pd.ExcelFile) -> dict[str, object]:
    if FINAL_CONDITIONS_SHEET not in xls.sheet_names:
        return {}
    try:
        frame = pd.read_excel(xls, sheet_name=FINAL_CONDITIONS_SHEET, header=1)
    except Exception:
        return {}
    if not {"확인항목", "입력값"}.issubset(frame.columns):
        return {}
    result: dict[str, object] = {}
    for _, row in frame.iterrows():
        question = _clean_text(row.get("확인항목"))
        if not question:
            continue
        result[question] = row.get("입력값")
    return result


def _read_optional_psm_note8(xls: pd.ExcelFile) -> pd.DataFrame:
    sheet_name = ""
    if PSM_NOTE8_SHEET in xls.sheet_names:
        sheet_name = PSM_NOTE8_SHEET
    elif LEGACY_PSM_NOTE8_SHEET in xls.sheet_names:
        sheet_name = LEGACY_PSM_NOTE8_SHEET
    if not sheet_name:
        return pd.DataFrame()
    try:
        frame = pd.read_excel(xls, sheet_name=sheet_name, header=2)
    except Exception:
        return pd.DataFrame()
    if frame.empty:
        return frame
    frame = frame.dropna(how="all").copy()
    if "적용여부" in frame.columns:
        status = frame["적용여부"].map(_clean_text)
        frame = frame[~status.isin(["해당없음", "미해당", "N", "n", ""])].copy()
    frame.reset_index(drop=True, inplace=True)
    return frame


def _condition_value(conditions: dict[str, object], token: str) -> str:
    for key, value in conditions.items():
        if token in _clean_text(key):
            return _clean_text(value)
    return ""


def _answer_is_yes(value: object) -> bool:
    return _norm_answer(value) in {"y", "yes", "예", "해당", "있음"}


def _answer_is_no(value: object) -> bool:
    return _norm_answer(value) in {"n", "no", "아니오", "해당없음", "미해당", "없음"}


def _answer_is_unknown(value: object) -> bool:
    return _norm_answer(value) in {"모름", "잘모름", "unknown", "미확인"}


def _map_sds_text_to_app1_keys(text: object) -> tuple[list[str], bool]:
    """Map company-entered SDS Section 2 text to approved Appendix-1 options.

    This uses exact hazard-group/category text only. It does not infer hazards
    from a chemical name, CAS number, or concentration.
    """
    raw = _clean_text(text)
    if not raw:
        return [], False
    compact = raw.replace(" ", "")
    if compact in {"해당없음", "별표1해당없음", "별표1유해성그룹해당없음"}:
        return [], True

    try:
        from .cap_sds_app1 import app1_sds_options
        options = app1_sds_options()
    except Exception:
        return [], False

    entries = [part.strip() for part in re.split(r"[|;\n]+", raw) if part.strip()]
    selected: list[str] = []
    for entry in entries:
        m = re.search(r"(.+?)(?:[:：]|\s)+구분\s*([0-9]+)", entry)
        if not m:
            continue
        group_text = "".join(ch for ch in m.group(1).strip().lower() if ch.isalnum())
        category = int(m.group(2))
        for option in options:
            option_group = "".join(ch for ch in option.hazard_group.strip().lower() if ch.isalnum())
            if option_group == group_text and option.category_no == category:
                selected.append(option.key)
                break
    return list(dict.fromkeys(selected)), False


def _seed_streamlit_session(data: IntakeData) -> None:
    """Prefill existing UI answers from the uploaded workbook when possible.

    The import is intentionally lazy so non-Streamlit unit tests can continue to
    use this module. Values are seeded only once per uploaded workbook and never
    overwrite choices the user makes afterward.
    """
    try:
        import streamlit as st
        session = st.session_state
    except Exception:
        return

    fingerprint = data.source_fingerprint
    if not fingerprint:
        return

    old = str(session.get("_intake_prefill_fingerprint", ""))
    if old and old != fingerprint:
        fixed_keys = {
            "simple_psm_exclusion", "simple_psm_note8", "simple_cap_holding_basis",
            "cap_final_exemption", "cap_final_exemption_all", "cap_major_facility",
        }
        for key in list(session.keys()):
            if key in fixed_keys or str(key).startswith("sds_app1_"):
                try:
                    del session[key]
                except Exception:
                    pass
    session["_intake_prefill_fingerprint"] = fingerprint

    conditions = data.final_conditions

    psm_exclusion = _condition_value(conditions, "시행령 제43조제2항 제외설비 해당 여부") or _condition_value(conditions, "법정 제외설비 해당 여부")
    if "simple_psm_exclusion" not in session and psm_exclusion:
        if _answer_is_no(psm_exclusion):
            session["simple_psm_exclusion"] = "해당 없음"
        elif _answer_is_unknown(psm_exclusion):
            session["simple_psm_exclusion"] = "모름"
        elif not _answer_is_yes(psm_exclusion):
            session["simple_psm_exclusion"] = psm_exclusion

    gas_special = _condition_value(conditions, "가스를 전문으로 저장·판매")
    if "simple_psm_note8" not in session and gas_special:
        if _answer_is_yes(gas_special):
            session["simple_psm_note8"] = "예, 해당하는 가스가 있습니다"
        elif _answer_is_no(gas_special):
            session["simple_psm_note8"] = "아니오, 해당하는 가스가 없습니다"
        elif _answer_is_unknown(gas_special):
            session["simple_psm_note8"] = "잘 모르겠습니다"

    partial_exemption = _condition_value(conditions, "법 제23조제1항 단서가 일부 취급시설에만 해당하는지") or _condition_value(conditions, "일부 시설만 면제조건")
    exemption = _condition_value(conditions, "법 제23조제1항 단서 해당 여부") or _condition_value(conditions, "법정 작성 면제시설 해당 여부")
    if "cap_final_exemption" not in session:
        if _answer_is_yes(partial_exemption):
            session["cap_final_exemption"] = "PARTIAL"
        elif _answer_is_no(exemption):
            session["cap_final_exemption"] = "NONE"
        elif _answer_is_unknown(exemption) or _answer_is_yes(exemption):
            # A bare 'Y' does not identify which statutory exemption applies.
            session["cap_final_exemption"] = "UNKNOWN"

    major = _condition_value(conditions, "개별 주요취급시설 존재 여부")
    if "cap_major_facility" not in session and major:
        if _answer_is_yes(major):
            session["cap_major_facility"] = "YES"
        elif _answer_is_no(major):
            session["cap_major_facility"] = "NO"
        elif _answer_is_unknown(major):
            session["cap_major_facility"] = "UNKNOWN"

    holding_col = "최대보유량 법정 산정 여부"
    holding_answers = []
    if holding_col in data.chemicals.columns:
        holding_answers = [_clean_text(v) for v in data.chemicals[holding_col].tolist() if _clean_text(v)]
    if "simple_cap_holding_basis" not in session:
        if not data.facilities.empty:
            # The facility sheet supplies the facts needed for Appendix-4 calculation.
            session["simple_cap_holding_basis"] = "예, 법정 산정방식으로 계산한 값입니다"
        elif holding_answers and all(_answer_is_yes(v) or _norm_answer(v) == "해당없음" for v in holding_answers):
            session["simple_cap_holding_basis"] = "예, 법정 산정방식으로 계산한 값입니다"
        elif any(_answer_is_unknown(v) for v in holding_answers):
            session["simple_cap_holding_basis"] = "잘 모르겠습니다"
        elif any(_answer_is_no(v) for v in holding_answers):
            session["simple_cap_holding_basis"] = "아니오, 단순 재고량 또는 임의값입니다"

    global_sds_match = _condition_value(conditions, "KOSHA 자동조회 분류와 일치")
    sds_status_col = "회사/제품 SDS 제2항 보유·확인 여부"
    sds_text_col = "SDS 제2항 유해성·위험성 분류(선택 입력)"
    for idx, row in data.chemicals.iterrows():
        row_no = idx + 1
        sds_status = _clean_text(row.get(sds_status_col)) if sds_status_col in row.index else ""
        sds_text = row.get(sds_text_col) if sds_text_col in row.index else ""
        selected, verified_none = _map_sds_text_to_app1_keys(sds_text)
        if selected or verified_none:
            session.setdefault(f"sds_app1_{row_no}_manual_mode", True)
            if selected:
                session.setdefault(f"sds_app1_{row_no}_classes", selected)
            if verified_none:
                session.setdefault(f"sds_app1_{row_no}_none", True)
        elif _answer_is_yes(global_sds_match) and _answer_is_yes(sds_status):
            session.setdefault(f"sds_app1_{row_no}_auto_confirmed", True)
        elif _norm_answer(global_sds_match) in {"n", "no", "아니오"} and _answer_is_yes(sds_status):
            session.setdefault(f"sds_app1_{row_no}_manual_mode", True)


def read_intake_workbook(file_bytes: bytes) -> IntakeData:
    xls = pd.ExcelFile(BytesIO(file_bytes), engine="openpyxl")
    missing_sheets = [s for s in [BUSINESS_SHEET, CHEM_SHEET, DOCS_SHEET] if s not in xls.sheet_names]
    if missing_sheets:
        raise ValueError("필수 시트가 없습니다: " + ", ".join(missing_sheets))

    business_df = pd.read_excel(xls, sheet_name=BUSINESS_SHEET, header=2)
    if not {"항목", "입력값"}.issubset(business_df.columns):
        raise ValueError("사업장 기본정보 시트 형식이 변경되었습니다.")
    business = {
        _clean_text(row["항목"]): row["입력값"]
        for _, row in business_df.iterrows()
        if _clean_text(row.get("항목"))
    }

    chemicals = pd.read_excel(xls, sheet_name=CHEM_SHEET, header=2)
    missing_cols = [c for c in REQUIRED_CHEM_COLUMNS if c not in chemicals.columns]
    if missing_cols:
        raise ValueError("화학물질 목록의 필수 열이 없습니다: " + ", ".join(missing_cols))
    chemicals = chemicals.dropna(how="all").copy()
    if "No." in chemicals.columns:
        chemical_value_cols = [c for c in chemicals.columns if c != "No."]
        chemicals = chemicals[chemicals[chemical_value_cols].notna().any(axis=1)].copy()
    chemicals.reset_index(drop=True, inplace=True)

    docs_df = pd.read_excel(xls, sheet_name=DOCS_SHEET, header=2)
    documents: dict[str, object] = {}
    if {"자료", "보유 여부"}.issubset(docs_df.columns):
        documents = {
            _clean_text(row["자료"]): row["보유 여부"]
            for _, row in docs_df.iterrows()
            if _clean_text(row.get("자료"))
        }

    data = IntakeData(
        business=business,
        chemicals=chemicals,
        documents=documents,
        facilities=_read_optional_facilities(xls),
        final_conditions=_read_optional_final_conditions(xls),
        psm_note8_exclusions=_read_optional_psm_note8(xls),
        mixture_components=_read_optional_mixture_components(xls),
        source_fingerprint=sha256(file_bytes).hexdigest(),
    )
    _apply_mixture_component_summary(data)
    return data


def validate_intake(data: IntakeData) -> list[str]:
    issues: list[str] = []
    for field in ["사업장명", "사업장 주소", "업종 또는 주요 생산품"]:
        if not _clean_text(data.business.get(field)):
            issues.append(f"사업장 기본정보: '{field}' 입력 필요")

    if data.chemicals.empty:
        issues.append("화학물질 목록: 입력된 물질이 없습니다.")
        return list(dict.fromkeys(issues + _mixture_validation_issues(data)))

    for idx, row in data.chemicals.iterrows():
        row_no = idx + 1
        cas = _clean_text(row.get("CAS No."))
        product = _clean_text(row.get("제품명"))
        if not cas and not product:
            issues.append(f"화학물질 {row_no}: 제품명 또는 CAS No. 중 하나는 필요합니다.")
        unit = _clean_text(row.get("수량 단위"))
        if not unit:
            issues.append(f"화학물질 {row_no}: 수량 단위가 필요합니다.")
        quantities = [row.get(col) for col in QUANTITY_COLUMNS if col in row.index]
        if not any(pd.notna(v) and _clean_text(v) != "" for v in quantities):
            issues.append(f"화학물질 {row_no}: 최대 제조·사용량, 최대 저장량 또는 최대 동시보유량 중 하나는 필요합니다.")

    return list(dict.fromkeys(issues + _mixture_validation_issues(data)))


def inventory_preview(data: IntakeData, columns: Iterable[str] | None = None) -> pd.DataFrame:
    if columns is None:
        columns = [
            "제품명", "CAS No.", "물질명(알면 입력)", "함량(%)", "취급형태",
            "최대 제조·사용량", "최대 저장량", "수량 단위", "최대 동시보유량(알면 입력)",
            "상온·상압 액체 여부(해당 시)", "최대보유량 법정 산정 여부",
            "회사/제품 SDS 제2항 보유·확인 여부",
        ]
    selected = [c for c in columns if c in data.chemicals.columns]
    return data.chemicals[selected].copy()
