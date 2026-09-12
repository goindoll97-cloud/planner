from pathlib import Path

STAGE1 = Path('engine/stage1_workbook.py')
TEMPLATE = Path('engine/template.py')
INIT = Path('engine/__init__.py')
UI = Path('ui/diagnosis_page.py')
TEST_TEMPLATE = Path('tests/test_template_contract.py')

stage1 = STAGE1.read_text(encoding='utf-8')

helper_marker = "def _row_label(intake: IntakeData, row_no: int) -> str:\n"
if '_build_psm_submission_explanation' not in stage1:
    helpers = r'''
_PSM_INDUSTRY_CLAUSE_BY_CODE = {
    "19210": 1,
    "19229": 2,
    "20111": 3,
    "20202": 3,
    "20311": 4,
    "20312": 5,
    "20321": 6,
    "20494": 7,
}


def _fmt_kg(value: object) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "수량 미확인"
    if amount >= 1000:
        return f"{amount / 1000:,.3f} ton ({amount:,.0f} kg)"
    return f"{amount:,.0f} kg"


def _fmt_ton(value: object) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "수량 미확인"
    return f"{amount:,.4g} ton"


def _build_psm_submission_explanation(psm_result) -> str:
    """Explain why the uploaded company facts satisfy the statutory PSM route."""
    parts = [
        "「산업안전보건법」 제44조제1항은 사업장에 대통령령으로 정하는 유해하거나 위험한 설비가 있는 경우 "
        "공정안전보고서를 작성하여 고용노동부장관에게 제출하도록 규정합니다."
    ]

    if psm_result.industry_trigger:
        code = str(psm_result.base.industry_code or "").strip()
        name = str(psm_result.base.industry_match or "").strip() or "해당 사업 종류"
        clause = _PSM_INDUSTRY_CLAUSE_BY_CODE.get(code)
        if clause:
            sentence = (
                f"귀 사업장이 입력한 한국표준산업분류 코드는 {code}이고, 이는 「산업안전보건법 시행령」 "
                f"제43조제1항제{clause}호의 ‘{name}’에 해당합니다."
            )
        else:
            sentence = (
                f"귀 사업장이 입력한 사업 종류는 「산업안전보건법 시행령」 제43조제1항 각 호의 ‘{name}’에 해당합니다."
            )
        if code == "20202":
            sentence += (
                " 이 사업 종류는 같은 항 제3호 단서에 따라 별표 13 제1호 인화성 가스 또는 제2호 인화성 액체에 "
                "해당하는 경우로 한정되며, 회사 입력정보에서 해당 조건이 확인되었습니다."
            )
        parts.append(sentence)

    if psm_result.quantity_trigger:
        detail_lines = []
        for line in sorted(psm_result.ratio_lines, key=lambda x: float(x.controlling_ratio or 0.0), reverse=True):
            if float(line.controlling_ratio or 0.0) <= 0:
                continue
            if line.controlling_basis == "저장":
                amount = line.storage_kg
                threshold = line.storage_threshold_kg
                ratio = line.storage_ratio
            else:
                amount = line.manufacture_handling_kg
                threshold = line.manufacture_handling_threshold_kg
                ratio = line.manufacture_handling_ratio
            detail_lines.append(
                f"별표 13 제{line.legal_item_no}호 {line.legal_substance}: {line.controlling_basis} "
                f"{_fmt_kg(amount)} / 규정량 {_fmt_kg(threshold)} = {float(ratio):.4f}"
            )
        shown = detail_lines[:5]
        suffix = f" 외 {len(detail_lines) - 5}개 항목" if len(detail_lines) > 5 else ""
        detail_text = "; ".join(shown) + suffix if shown else "별표 13 해당 물질의 규정량 비교 결과"
        parts.append(
            f"또한 「산업안전보건법 시행령」 제43조제1항 및 별표 13 비고 제7호에 따라 산정한 합산한 값(R)이 "
            f"{float(psm_result.r_value):.4f}로 1 이상입니다. 주요 산정근거는 {detail_text}입니다."
        )

    parts.append(
        "회사 입력정보에서 「산업안전보건법 시행령」 제43조제2항 각 호의 제외설비에 해당하지 않는 것으로 확인되어, "
        "귀 사업장은 공정안전보고서 제출 대상에 포함됩니다."
    )
    return " ".join(parts)


def _cap_level(row: dict[str, Any]) -> str:
    raw = str(row.get("quantity_band") or row.get("status") or "")
    upper = raw.upper()
    if "BELOW" in upper or "하위 규정수량 미만" in raw:
        return "BELOW"
    if "UPPER" in upper or "상위 규정수량 이상" in raw:
        return "UPPER"
    if "LOWER" in upper or "하위 이상" in raw or "하위 규정수량 이상" in raw:
        return "LOWER"
    return ""


def _cap_row_summary(row: dict[str, Any], level: str) -> str:
    name = str(row.get("product_name") or row.get("legal_substance") or "해당 유해화학물질").strip()
    cas = str(row.get("cas") or "").strip()
    label = f"{name}" + (f"(CAS {cas})" if cas else "")
    holding = row.get("calculated_max_holding_ton")
    if holding is None:
        holding = row.get("confirmed_max_holding_ton")
    lower = row.get("lower_quantity_ton")
    upper = row.get("upper_quantity_ton")
    if level == "UPPER":
        if holding is not None and upper is not None:
            return f"{label}의 사업장 최대보유량 {_fmt_ton(holding)}이 상위 규정수량 {_fmt_ton(upper)} 이상"
        return f"{label}의 사업장 최대보유량이 상위 규정수량 이상"
    if level == "LOWER":
        if holding is not None and lower is not None and upper is not None:
            return (
                f"{label}의 사업장 최대보유량 {_fmt_ton(holding)}이 하위 규정수량 {_fmt_ton(lower)} 이상이고 "
                f"상위 규정수량 {_fmt_ton(upper)} 미만"
            )
        return f"{label}의 사업장 최대보유량이 하위 규정수량 이상·상위 규정수량 미만"
    return label


def _build_cap_required_explanation(final_cap, quantity_rows: list[dict[str, Any]]) -> str:
    """Explain why the uploaded company facts require a CAP and its writing level."""
    parts = [
        "「화학물질관리법」 제23조제1항은 유해화학물질 취급시설을 설치·운영하려는 자에게 "
        "화학사고예방관리계획서를 작성하여 제출하도록 규정합니다."
    ]
    if final_cap.status == "REQUIRED_GROUP_1":
        matched = [_cap_row_summary(row, "UPPER") for row in quantity_rows if _cap_level(row) == "UPPER"]
        matched = list(dict.fromkeys(matched))
        if matched:
            parts.append("귀 사업장의 규정수량 비교 결과, " + "; ".join(matched[:5]) + "으로 확인되었습니다.")
        parts.append(
            "또한 회사 입력정보에서 「화학물질관리법 시행규칙」 제19조제8항에 따른 주요취급시설을 운영하는 것으로 "
            "확인되었고, 「화학물질관리법」 제23조제1항 단서의 법정 예외에 해당하지 않는 것으로 확인되었습니다."
        )
        parts.append(
            "따라서 「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제1항제12의1, 제4조 및 제6조에 따라 "
            "귀 사업장은 화학사고예방관리계획서 작성수준 1군 사업장으로 작성·제출 대상에 포함됩니다."
        )
    elif final_cap.status == "REQUIRED_GROUP_2":
        matched = [_cap_row_summary(row, "LOWER") for row in quantity_rows if _cap_level(row) == "LOWER"]
        matched = list(dict.fromkeys(matched))
        if matched:
            parts.append("귀 사업장의 규정수량 비교 결과, " + "; ".join(matched[:5]) + "으로 확인되었습니다.")
        parts.append("회사 입력정보에서 「화학물질관리법」 제23조제1항 단서의 법정 예외에 해당하지 않는 것으로 확인되었습니다.")
        parts.append(
            "따라서 「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제1항제12의2, 제4조 및 제6조에 따라 "
            "귀 사업장은 화학사고예방관리계획서 작성수준 2군 사업장으로 작성·제출 대상에 포함됩니다."
        )
    return " ".join(parts)


'''
    if helper_marker not in stage1:
        raise SystemExit('stage1 helper marker not found')
    stage1 = stage1.replace(helper_marker, helpers + helper_marker, 1)

old_psm = '''                if _answer_is_no(exclusion_raw):
                    decision.psm_status = "공정안전보고서 제출 대상"
                    decision.psm_explanation = "「산업안전보건법 시행령」 제43조제1항의 사업 종류 또는 별표 13 유해·위험물질 규정량 기준에 해당하고, 제43조제2항 제외설비에 해당하지 않는 것으로 회사 입력파일에서 확인되었습니다."
'''
new_psm = '''                if _answer_is_no(exclusion_raw):
                    decision.psm_status = "공정안전보고서 제출 대상"
                    decision.psm_explanation = _build_psm_submission_explanation(psm_result)
'''
if old_psm not in stage1:
    raise SystemExit('PSM explanation block not found')
stage1 = stage1.replace(old_psm, new_psm, 1)

old_psm_basis = '        decision.psm_legal_basis = ["「산업안전보건법 시행령」 제43조", "같은 영 별표 13"]\n'
new_psm_basis = '''        decision.psm_legal_basis = [
            "「산업안전보건법」 제44조제1항",
            "「산업안전보건법 시행령」 제43조제1항",
            "같은 영 제43조제2항",
        ]
        if psm_result.quantity_trigger:
            decision.psm_legal_basis.append("같은 영 별표 13 및 비고 제7호")
'''
if old_psm_basis not in stage1:
    raise SystemExit('PSM legal basis block not found')
stage1 = stage1.replace(old_psm_basis, new_psm_basis, 1)

old_cap = '''    decision.cap_status = final_cap.label
    if final_cap.status == "REQUIRED_GROUP_1":
        decision.cap_explanation = "회사 입력파일의 최대보유량, 상위 규정수량, 법적 예외 및 주요취급시설 정보를 기준으로 작성수준을 1군 사업장으로 확인했습니다."
    elif final_cap.status == "REQUIRED_GROUP_2":
        decision.cap_explanation = "회사 입력파일의 최대보유량, 하위·상위 규정수량 및 법적 예외 정보를 기준으로 작성수준을 2군 사업장으로 확인했습니다."
    elif final_cap.status == "NOT_REQUIRED":
        decision.cap_explanation = "회사 입력파일과 승인 규정 DB를 기준으로 화학사고예방관리계획서 작성·제출 의무가 없는 사유를 확인했습니다."
    else:
        decision.cap_explanation = "회사 입력파일의 미확인 항목을 보완해야 최종 작성 여부 또는 작성수준을 확정할 수 있습니다."
    decision.cap_legal_basis = list(final_cap.legal_basis)
'''
new_cap = '''    decision.cap_status = final_cap.label
    if final_cap.status in {"REQUIRED_GROUP_1", "REQUIRED_GROUP_2"}:
        decision.cap_explanation = _build_cap_required_explanation(final_cap, quantity_rows)
    elif final_cap.status == "NOT_REQUIRED":
        decision.cap_explanation = "회사 입력정보와 승인 규정 DB를 기준으로 화학사고예방관리계획서 작성·제출 의무가 없는 사유를 확인했습니다."
    else:
        decision.cap_explanation = "회사 입력정보의 미확인 항목을 보완해야 최종 작성 여부 또는 작성수준을 확정할 수 있습니다."
    decision.cap_legal_basis = list(final_cap.legal_basis)
    if final_cap.status in {"REQUIRED_GROUP_1", "REQUIRED_GROUP_2"}:
        decision.cap_legal_basis = _unique([
            "「화학물질관리법」 제23조제1항",
            "「화학물질관리법 시행규칙」 제19조제1항",
            *decision.cap_legal_basis,
        ])
'''
if old_cap not in stage1:
    raise SystemExit('CAP explanation block not found')
stage1 = stage1.replace(old_cap, new_cap, 1)
STAGE1.write_text(stage1, encoding='utf-8')

# Make the law-reference workbook use full statutory names in its user-facing labels.
template = TEMPLATE.read_text(encoding='utf-8')
replacements = {
    '"PSM·화학사고예방관리계획서 법령 작성 참고"': '"공정안전보고서·화학사고예방관리계획서 법령 작성 참고"',
    '["공정안전보고서(PSM)", "2026-09-12 확인"': '["공정안전보고서", "2026-09-12 확인"',
    'build_reference_sheet("01_PSM_법령참고", psm_rows)': 'build_reference_sheet("01_공정안전보고서_법령참고", psm_rows)',
    'build_reference_sheet("02_화사계_법령참고", cap_rows)': 'build_reference_sheet("02_화학사고예방관리계획서_법령참고", cap_rows)',
}
for old, new in replacements.items():
    if old not in template:
        raise SystemExit(f'template replacement not found: {old}')
    template = template.replace(old, new)
TEMPLATE.write_text(template, encoding='utf-8')

init = INIT.read_text(encoding='utf-8')
init_replacements = {
    '"법령 작성 참고파일 다운로드"': '"공정안전보고서·화학사고예방관리계획서 법령 작성 참고파일 다운로드"',
    'file_name="PSM_CAP_법령작성참고_v1.0.xlsx"': 'file_name="공정안전보고서_화학사고예방관리계획서_법령작성참고_v1.1.xlsx"',
}
for old, new in init_replacements.items():
    if old not in init:
        raise SystemExit(f'init replacement not found: {old}')
    init = init.replace(old, new)
INIT.write_text(init, encoding='utf-8')

ui = UI.read_text(encoding='utf-8')
old_ui = '''        if explanation:\n            st.write(explanation)\n'''
new_ui = '''        if explanation:\n            st.markdown("**판정 근거 설명**")\n            st.write(explanation)\n'''
if old_ui not in ui:
    raise SystemExit('UI explanation block not found')
ui = ui.replace(old_ui, new_ui, 1)
UI.write_text(ui, encoding='utf-8')

# Update law-reference workbook contract names and ensure abbreviations are not used as section names.
test = TEST_TEMPLATE.read_text(encoding='utf-8')
test = test.replace(
    'self.assertEqual(legal.sheetnames, ["00_사용안내", "01_PSM_법령참고", "02_화사계_법령참고"])',
    'self.assertEqual(legal.sheetnames, ["00_사용안내", "01_공정안전보고서_법령참고", "02_화학사고예방관리계획서_법령참고"])'
)
test = test.replace('legal["01_PSM_법령참고"]', 'legal["01_공정안전보고서_법령참고"]')
test = test.replace('legal["02_화사계_법령참고"]', 'legal["02_화학사고예방관리계획서_법령참고"]')
needle = '        combined = psm_values + "\\n" + cap_values\n'
if needle not in test:
    raise SystemExit('template test insertion marker not found')
test = test.replace(
    needle,
    needle + '        guide_values = "\\n".join(str(c.value) for row in legal["00_사용안내"].iter_rows() for c in row if c.value is not None)\n'
             '        self.assertIn("공정안전보고서·화학사고예방관리계획서 법령 작성 참고", guide_values)\n'
             '        self.assertNotIn("공정안전보고서(PSM)", guide_values)\n',
    1,
)
TEST_TEMPLATE.write_text(test, encoding='utf-8')
