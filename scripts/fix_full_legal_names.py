from pathlib import Path

TEMPLATE = Path('engine/template.py')
INVENTORY = Path('engine/inventory.py')
STAGE1 = Path('engine/stage1_workbook.py')
UI = Path('ui/diagnosis_page.py')
TEMPLATE_TEST = Path('tests/test_template_contract.py')
DECISION_TEST = Path('tests/test_decision_explanation_contract.py')

# User-facing workbook text: use full statutory names, never shortened labels.
template = TEMPLATE.read_text(encoding='utf-8')
template = template.replace('PSM·화학사고예방관리계획서 법령 작성 참고', '공정안전보고서·화학사고예방관리계획서 법령 작성 참고')
template = template.replace('PSM·화학사고예방관리계획서 입력항목별 법령 작성 참고', '공정안전보고서·화학사고예방관리계획서 입력항목별 법령 작성 참고')
template = template.replace('공정안전보고서(PSM)', '공정안전보고서')
template = template.replace('06_PSM_비고8제외수량', '06_공정안전보고서_비고8제외수량')
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
DECISION_TEST.write_text(decision_test, encoding='utf-8')
