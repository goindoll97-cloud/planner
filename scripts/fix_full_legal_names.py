from pathlib import Path

TEMPLATE = Path('engine/template.py')
INVENTORY = Path('engine/inventory.py')
STAGE1 = Path('engine/stage1_workbook.py')
UI = Path('ui/diagnosis_page.py')
TEMPLATE_TEST = Path('tests/test_template_contract.py')
DECISION_TEST = Path('tests/test_decision_explanation_contract.py')

# User-facing workbook text: use full statutory names, never shortened labels.
template = TEMPLATE.read_text(encoding='utf-8')
replacements = {
    'PSM·화학사고예방관리계획서 법령 작성 참고': '공정안전보고서·화학사고예방관리계획서 법령 작성 참고',
    'PSM·화학사고예방관리계획서 입력항목별 법령 작성 참고': '공정안전보고서·화학사고예방관리계획서 입력항목별 법령 작성 참고',
    'PSM·화학사고예방관리계획서 회사 입력파일 작성가이드': '공정안전보고서·화학사고예방관리계획서 회사 입력파일 작성가이드',
    'PSM/화학사고예방관리계획서 물질기준': '공정안전보고서/화학사고예방관리계획서 물질기준',
    'PSM 시행령 제43조제2항 제외설비': '「산업안전보건법 시행령」 제43조제2항 제외설비',
    '화관법 제23조제1항 단서': '「화학물질관리법」 제23조제1항 단서',
    '공정안전보고서(PSM)': '공정안전보고서',
    'PSM 대상 판정 후': '공정안전보고서 제출 대상 판정 후',
    'PSM 별표 13 비고 제8호 제외수량': '공정안전보고서 관련 「산업안전보건법 시행령」 별표 13 비고 제8호 제외수량',
    'PSM 별표 13': '공정안전보고서 관련 「산업안전보건법 시행령」 별표 13',
    '06_PSM_비고8제외수량': '06_공정안전보고서_비고8제외수량',
}
for old, new in replacements.items():
    template = template.replace(old, new)
TEMPLATE.write_text(template, encoding='utf-8')

# Canonical company sheet name also uses the full legal name; old files remain readable.
inventory = INVENTORY.read_text(encoding='utf-8')
old_const = 'PSM_NOTE8_SHEET = "06_PSM_비고8제외수량"'
new_const = 'PSM_NOTE8_SHEET = "06_공정안전보고서_비고8제외수량"\nLEGACY_PSM_NOTE8_SHEET = "06_PSM_비고8제외수량"'
if old_const in inventory:
    inventory = inventory.replace(old_const, new_const, 1)
old_reader = '''def _read_optional_psm_note8(xls: pd.ExcelFile) -> pd.DataFrame:\n    if PSM_NOTE8_SHEET not in xls.sheet_names:\n        return pd.DataFrame()\n    try:\n        frame = pd.read_excel(xls, sheet_name=PSM_NOTE8_SHEET, header=2)\n'''
new_reader = '''def _read_optional_psm_note8(xls: pd.ExcelFile) -> pd.DataFrame:\n    sheet_name = ""\n    if PSM_NOTE8_SHEET in xls.sheet_names:\n        sheet_name = PSM_NOTE8_SHEET\n    elif LEGACY_PSM_NOTE8_SHEET in xls.sheet_names:\n        sheet_name = LEGACY_PSM_NOTE8_SHEET\n    if not sheet_name:\n        return pd.DataFrame()\n    try:\n        frame = pd.read_excel(xls, sheet_name=sheet_name, header=2)\n'''
if old_reader in inventory:
    inventory = inventory.replace(old_reader, new_reader, 1)
INVENTORY.write_text(inventory, encoding='utf-8')

stage1 = STAGE1.read_text(encoding='utf-8').replace('06_PSM_비고8제외수량', '06_공정안전보고서_비고8제외수량')
STAGE1.write_text(stage1, encoding='utf-8')

ui = UI.read_text(encoding='utf-8').replace('PSM_FULL = "공정안전보고서(PSM)"', 'PSM_FULL = "공정안전보고서"')
UI.write_text(ui, encoding='utf-8')

# Update old contract test to the new canonical names everywhere, including lookups.
test = TEMPLATE_TEST.read_text(encoding='utf-8')
test = test.replace('06_PSM_비고8제외수량', '06_공정안전보고서_비고8제외수량')
test = test.replace('01_PSM_법령참고', '01_공정안전보고서_법령참고')
test = test.replace('02_화사계_법령참고', '02_화학사고예방관리계획서_법령참고')
TEMPLATE_TEST.write_text(test, encoding='utf-8')

# Strengthen the new contract: reference workbook contains no shortened system names.
decision_test = DECISION_TEST.read_text(encoding='utf-8')
decision_test = decision_test.replace("self.assertNotIn('PSM·', joined)", "self.assertNotIn('PSM', joined)\n        self.assertNotIn('화사계', joined)")
# Also ensure the company workbook guide does not expose the common abbreviations.
if 'test_company_workbook_guide_uses_full_names' not in decision_test:
    insert = '''\n    def test_company_workbook_guide_uses_full_names(self) -> None:\n        from engine.template import build_minimal_input_workbook\n        wb = load_workbook(BytesIO(build_minimal_input_workbook()), data_only=False)\n        values = [str(cell.value or '') for ws in wb.worksheets for row in ws.iter_rows() for cell in row]\n        joined = '\\n'.join(values)\n        self.assertNotIn('PSM·', joined)\n        self.assertNotIn('화관법', joined)\n        self.assertNotIn('화사계', joined)\n        self.assertIn('공정안전보고서', joined)\n        self.assertIn('화학사고예방관리계획서', joined)\n'''
    marker = "\n    def test_download_filenames_do_not_use_abbreviations(self) -> None:\n"
    decision_test = decision_test.replace(marker, insert + marker, 1)
DECISION_TEST.write_text(decision_test, encoding='utf-8')
