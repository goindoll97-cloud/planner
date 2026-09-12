from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"pattern not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"updated {path}")


# ---------------- inventory.py ----------------
replace_once(
    "engine/inventory.py",
    'FINAL_CONDITIONS_SHEET = "05_최종판정조건"\n',
    'FINAL_CONDITIONS_SHEET = "05_최종판정조건"\nPSM_NOTE8_SHEET = "06_PSM_비고8제외수량"\n',
)
replace_once(
    "engine/inventory.py",
    '    final_conditions: dict[str, object] = field(default_factory=dict)\n    source_fingerprint: str = ""\n',
    '    final_conditions: dict[str, object] = field(default_factory=dict)\n    psm_note8_exclusions: pd.DataFrame = field(default_factory=pd.DataFrame)\n    source_fingerprint: str = ""\n',
)
replace_once(
    "engine/inventory.py",
    '''def _condition_value(conditions: dict[str, object], token: str) -> str:\n''',
    '''def _read_optional_psm_note8(xls: pd.ExcelFile) -> pd.DataFrame:\n    if PSM_NOTE8_SHEET not in xls.sheet_names:\n        return pd.DataFrame()\n    try:\n        frame = pd.read_excel(xls, sheet_name=PSM_NOTE8_SHEET, header=2)\n    except Exception:\n        return pd.DataFrame()\n    if frame.empty:\n        return frame\n    frame = frame.dropna(how="all").copy()\n    if "적용여부" in frame.columns:\n        status = frame["적용여부"].map(_clean_text)\n        frame = frame[~status.isin(["해당없음", "미해당", "N", "n", ""])].copy()\n    frame.reset_index(drop=True, inplace=True)\n    return frame\n\n\ndef _condition_value(conditions: dict[str, object], token: str) -> str:\n''',
)
replace_once(
    "engine/inventory.py",
    '''        final_conditions=_read_optional_final_conditions(xls),\n        source_fingerprint=sha256(file_bytes).hexdigest(),\n    )\n    _seed_streamlit_session(data)\n    return data\n''',
    '''        final_conditions=_read_optional_final_conditions(xls),\n        psm_note8_exclusions=_read_optional_psm_note8(xls),\n        source_fingerprint=sha256(file_bytes).hexdigest(),\n    )\n    return data\n''',
)

# ---------------- template.py ----------------
replace_once(
    "engine/template.py",
    '"제출·작성 의무 및 작성수준 결정", "05_최종판정조건 참고"],',
    '"제출·작성 의무 및 작성수준 결정", "05_최종판정조건·06_PSM_비고8제외수량 참고"],',
)
old_final = '''def _build_final_conditions_sheet(wb: Workbook) -> None:\n    ws = wb.create_sheet("05_최종판정조건")\n    ws.merge_cells("A1:F1")\n    ws["A1"] = "5. 최종 판정 조건 — 해당하지 않으면 '해당없음', 확인하지 못했으면 '모름'"\n    ws["A1"].fill = PSM_FILL\n    ws["A1"].font = Font(bold=True, size=13)\n    _write_row(ws, 2, ["제도", "확인항목", "입력값", "필수수준", "확인자료 예시", "판정에 미치는 영향"])\n    _style_header(ws, "A2:F2")\n\n    rows = [\n        ["공정안전보고서", "시행령 제43조제2항 제외설비 해당 여부", "해당없음", "조건부 필수", "설비 용도·인허가·도면", "공정안전보고서 제출 대상 여부"],\n        ["공정안전보고서", "가스를 전문으로 저장·판매하는 시설 내 가스 여부", "해당없음", "조건부 필수", "시설 용도·사업형태", "별표 13 비고 제7호 합산한 값(R) 산정"],\n        ["화학사고예방관리계획서", "법 제23조제1항 단서 해당 여부", "해당없음", "규정수량 이상 시 필수", "시설 용도·인허가·운영현황", "작성·제출 의무 여부"],\n        ["화학사고예방관리계획서", "법 제23조제1항 단서가 일부 취급시설에만 해당하는지", "해당없음", "조건부 필수", "시설별 적용범위", "최대보유량 재산정"],\n        ["화학사고예방관리계획서", "상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부", "Y", "상위 규정수량 해당 시 필수", "시설별 최대보유량·설계자료", "작성수준 1군/2군"],\n        ["화학사고예방관리계획서", "회사/제품 SDS 제2항이 KOSHA 자동조회 분류와 일치하는지", "Y", "자동조회 사용 시", "현재 공급자 SDS 제2항", "별표 1 규정수량 확정"],\n        ["공통", "미확인 결정조건 존재 여부", "N", "필수", "사내 검토", "Y면 판정보류"],\n    ]\n    for r_idx, row in enumerate(rows, start=3):\n        _write_row(ws, r_idx, row)\n        ws.cell(r_idx, 3).fill = EXAMPLE_FILL\n    _add_list_validation(ws, "C3:C9", ["Y", "N", "해당없음", "모름"])\n    _wrap_range(ws, "A1:F9")\n    widths = [26, 52, 16, 22, 36, 30]\n    for i, width in enumerate(widths, 1):\n        ws.column_dimensions[chr(64 + i)].width = width\n    ws.freeze_panes = "A3"\n'''
new_final = '''def _build_final_conditions_sheet(wb: Workbook) -> None:\n    ws = wb.create_sheet("05_최종판정조건")\n    ws.merge_cells("A1:F1")\n    ws["A1"] = "5. 최종 판정 조건 — 회사에서 확인한 사실을 Excel에 직접 작성"\n    ws["A1"].fill = PSM_FILL\n    ws["A1"].font = Font(bold=True, size=13)\n    _write_row(ws, 2, ["제도", "확인항목", "입력값", "필수수준", "확인자료 예시", "판정에 미치는 영향"])\n    _style_header(ws, "A2:F2")\n\n    rows = [\n        ["공정안전보고서", "시행령 제43조제2항 제외설비 해당 여부", "N", "조건부 필수", "설비 용도·인허가·도면", "공정안전보고서 제출 대상 여부"],\n        ["공정안전보고서", "시행령 제43조제2항 제외설비 유형", "해당없음", "해당 시 필수", "법령상 제외설비 유형을 그대로 작성", "제외설비 법적 유형 확인"],\n        ["공정안전보고서", "별표 13 제1호 인화성 가스 해당 여부", "N", "조건부 필수", "회사 SDS·공정안전자료", "별표 13 제1호 적용 여부"],\n        ["공정안전보고서", "별표 13 제1호 하루 최대 제조·취급량(kg)", 0, "제1호 해당 시 필수", "하루 최대 제조·취급량", "비고 제7호 합산한 값(R)"],\n        ["공정안전보고서", "별표 13 제1호 최대 저장량(kg)", 0, "제1호 해당 시 필수", "최대 저장량", "비고 제7호 합산한 값(R)"],\n        ["공정안전보고서", "별표 13 제2호 인화성 액체 해당 여부", "N", "조건부 필수", "회사 SDS·공정안전자료", "별표 13 제2호 적용 여부"],\n        ["공정안전보고서", "별표 13 제2호 하루 최대 제조·취급량(kg)", 0, "제2호 해당 시 필수", "하루 최대 제조·취급량", "비고 제7호 합산한 값(R)"],\n        ["공정안전보고서", "별표 13 제2호 최대 저장량(kg)", 0, "제2호 해당 시 필수", "최대 저장량", "비고 제7호 합산한 값(R)"],\n        ["공정안전보고서", "별표 13 제23호 발연황산 삼산화황(SO3) 중량%", "해당없음", "해당 물질 보유 시 필수", "제품 SDS·성분분석자료", "별표 13 제23호 성분조건"],\n        ["공정안전보고서", "별표 13 제42호 니트로셀룰로오스 질소 함유량%", "해당없음", "해당 물질 보유 시 필수", "제품 SDS·성분분석자료", "별표 13 제42호 성분조건"],\n        ["공정안전보고서", "가스를 전문으로 저장·판매하는 시설 내 가스 여부", "N", "조건부 필수", "시설 용도·사업형태", "별표 13 비고 제8호"],\n        ["화학사고예방관리계획서", "법 제23조제1항 단서 해당 여부", "N", "규정수량 이상 시 필수", "시설 용도·인허가·운영현황", "작성·제출 의무 여부"],\n        ["화학사고예방관리계획서", "법적 예외 적용 유형", "해당없음", "해당 시 필수", "법 제23조제1항 단서·시행규칙 제19조제2항·고시 제9조의 유형", "법적 예외 유형 확인"],\n        ["화학사고예방관리계획서", "법적 예외가 관련 취급시설 전체에 적용되는지", "Y", "해당 시 필수", "시설별 적용범위", "전체 적용 여부"],\n        ["화학사고예방관리계획서", "상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부", "Y", "상위 규정수량 해당 시 필수", "시설별 최대보유량·설계자료", "작성수준 1군/2군"],\n        ["화학사고예방관리계획서", "회사/제품 SDS 제2항이 KOSHA 자동조회 분류와 일치하는지", "Y", "자동조회 사용 시", "현재 공급자 SDS 제2항", "별표 1 규정수량 확정"],\n        ["공통", "미확인 결정조건 존재 여부", "N", "필수", "사내 검토", "Y면 판정보류"],\n    ]\n    for r_idx, row in enumerate(rows, start=3):\n        _write_row(ws, r_idx, row)\n        ws.cell(r_idx, 3).fill = EXAMPLE_FILL\n\n    for cell in ["C3", "C5", "C8", "C13", "C14", "C16", "C17", "C18", "C19"]:\n        _add_list_validation(ws, cell, ["Y", "N", "해당없음", "모름"])\n    _wrap_range(ws, "A1:F19")\n    widths = [26, 58, 20, 24, 40, 32]\n    for i, width in enumerate(widths, 1):\n        ws.column_dimensions[chr(64 + i)].width = width\n    ws.freeze_panes = "A3"\n\n\ndef _build_psm_note8_sheet(wb: Workbook) -> None:\n    ws = wb.create_sheet("06_PSM_비고8제외수량")\n    ws.merge_cells("A1:G1")\n    ws["A1"] = "6. PSM 별표 13 비고 제8호 제외수량 — 전문 가스 저장·판매시설에 해당할 때만 작성"\n    ws["A1"].fill = PSM_FILL\n    ws["A1"].font = Font(bold=True, size=13)\n    ws.merge_cells("A2:G2")\n    ws["A2"] = "※ 05_최종판정조건에서 '가스를 전문으로 저장·판매하는 시설 내 가스 여부=Y'인 경우에만 작성합니다. 시설 하나당 한 줄로 작성하세요."\n    ws["A2"].fill = NOTE_FILL\n    ws["A2"].alignment = Alignment(wrap_text=True)\n    headers = ["적용여부", "별표13 호수", "제조·취급 제외량(kg)", "저장 제외량(kg)", "시설명", "근거", "비고"]\n    _write_row(ws, 3, headers)\n    _style_header(ws, "A3:G3")\n    _write_row(ws, 4, ["해당없음", None, None, None, None, None, "비고 제8호 미해당이면 이 시트는 작성하지 않아도 됩니다."])\n    _fill_range(ws, "A4:G4", EXAMPLE_FILL)\n    for r in range(5, 31):\n        for c in range(1, 8):\n            ws.cell(r, c).fill = INPUT_FILL\n    _add_list_validation(ws, "A4:A30", ["해당", "해당없음", "모름"])\n    _wrap_range(ws, "A1:G30")\n    widths = [12, 14, 24, 20, 26, 38, 38]\n    for i, width in enumerate(widths, 1):\n        ws.column_dimensions[chr(64 + i)].width = width\n    ws.freeze_panes = "A4"\n'''
replace_once("engine/template.py", old_final, new_final)
replace_once(
    "engine/template.py",
    '''    _build_final_conditions_sheet(wb)\n\n    output = BytesIO()\n''',
    '''    _build_final_conditions_sheet(wb)\n    _build_psm_note8_sheet(wb)\n\n    output = BytesIO()\n''',
)

print("excel source-of-truth workbook refactor applied")
