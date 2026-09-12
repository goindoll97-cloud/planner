from pathlib import Path

path = Path('engine/stage1_workbook.py')
text = path.read_text(encoding='utf-8')
old = 'from .cap_final_decision import assess_cap_final, exemption_options'
new = 'from .cap_final_decision import assess_cap_final, exemption_options, normalize_quantity_evidence'
if old not in text:
    if new in text:
        raise SystemExit(0)
    raise SystemExit('import target not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
