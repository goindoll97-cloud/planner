from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Iterable

import pandas as pd


CHEM_SHEET = "02_화학물질목록"
BUSINESS_SHEET = "01_사업장기본정보"
DOCS_SHEET = "03_기존문서보유여부"

REQUIRED_CHEM_COLUMNS = ["제품명", "CAS No.", "함량(%)", "취급형태", "수량 단위"]
QUANTITY_COLUMNS = ["최대 제조·사용량", "최대 저장량", "최대 동시보유량(알면 입력)"]


@dataclass
class IntakeData:
    business: dict[str, object]
    chemicals: pd.DataFrame
    documents: dict[str, object]


def _clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


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

    return IntakeData(business=business, chemicals=chemicals, documents=documents)


def validate_intake(data: IntakeData) -> list[str]:
    issues: list[str] = []
    for field in ["사업장명", "사업장 주소", "업종 또는 주요 생산품"]:
        if not _clean_text(data.business.get(field)):
            issues.append(f"사업장 기본정보: '{field}' 입력 필요")

    if data.chemicals.empty:
        issues.append("화학물질 목록: 입력된 물질이 없습니다.")
        return issues

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

    return issues


def inventory_preview(data: IntakeData, columns: Iterable[str] | None = None) -> pd.DataFrame:
    if columns is None:
        columns = [
            "제품명", "CAS No.", "물질명(알면 입력)", "함량(%)", "취급형태",
            "최대 제조·사용량", "최대 저장량", "수량 단위", "최대 동시보유량(알면 입력)",
        ]
    selected = [c for c in columns if c in data.chemicals.columns]
    return data.chemicals[selected].copy()
