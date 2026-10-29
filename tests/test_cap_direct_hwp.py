from engine.stage2.cap_direct_hwp import build_partial_hwp
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.evidence_workspace import read_document


def test_partial_hwp_contains_company_in_original_input_cell():
    project = create_direct_cap_project('가상새솔화학', cap_group='1군')
    data = build_partial_hwp(project)
    tables, _ = read_document('draft.hwp', data)
    assert len(tables) == 45
    assert tables[12].rows[1][:2] == ['사업장명', '가상새솔화학']
    assert tables[16].rows[0][0] == '취급물질의 일반정보'
