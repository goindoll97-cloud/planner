from pathlib import Path

TEMPLATE = Path('engine/template.py')
STAGE1 = Path('engine/stage1_workbook.py')
TEST = Path('tests/test_decision_explanation_contract.py')

template = TEMPLATE.read_text(encoding='utf-8')
for old, new in {
    '"PSM"': '"공정안전보고서"',
    '기존 PSM 보유 여부': '기존 공정안전보고서 보유 여부',
    'PSM 대상 판정 후': '공정안전보고서 제출 대상 판정 후',
    'PSM 별표': '공정안전보고서 관련 「산업안전보건법 시행령」 별표',
}.items():
    template = template.replace(old, new)
TEMPLATE.write_text(template, encoding='utf-8')

stage1 = STAGE1.read_text(encoding='utf-8')
stage1 = stage1.replace('의 PSM 수량을 kg 또는 ton 질량단위로 작성해 주세요.', '의 공정안전보고서 판정 수량을 kg 또는 ton 질량단위로 작성해 주세요.')
STAGE1.write_text(stage1, encoding='utf-8')

test = TEST.read_text(encoding='utf-8')
test = test.replace("self.assertNotIn('PSM·', joined)", "self.assertNotIn('PSM', joined)")
if "self.assertNotIn('PSM', joined)" not in test:
    raise SystemExit('company workbook abbreviation assertion was not installed')
TEST.write_text(test, encoding='utf-8')
