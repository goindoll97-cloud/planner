from copy import deepcopy
from io import BytesIO

from docx import Document
from hwpx import HwpxDocument
import pytest

from engine.stage2 import cap_baseline_docx as baseline, cap_direct_hwp as direct, cap_fact_drafting, report_export
from engine.stage2 import company_workbook_intake as intake, demo_company_workbook as demo, scenario_pipeline
from engine.stage2.cap_baseline_docx import load_cap_baseline_bytes
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.evidence_workspace import read_document
from engine.stage2.hwp5_binary import HWP5_MAGIC, to_hwpx
from engine.stage2.project import Stage2Project


@pytest.fixture
def demo_docx(tmp_path, monkeypatch) -> bytes:
    """가상 회사 엑셀을 올려 서술형·시나리오까지 작성한 실제 DOCX 초안."""
    monkeypatch.chdir(tmp_path)
    project = intake.project_for_upload(Stage2Project(project_id='HWP-DEMO', company_name=''), demo.FILENAME, demo.build())
    intake.apply(project, demo.FILENAME, demo.build())
    cap_fact_drafting.generate(project)
    scenario_pipeline.refresh(project)
    return report_export.build_cap_workspace_draft(project).docx


def _opened(hwp: bytes):
    assert hwp.startswith(HWP5_MAGIC)
    return HwpxDocument.open(to_hwpx(hwp))


def _pairs(docx: bytes, doc) -> list:
    return direct._table_pairs(Document(BytesIO(docx)), Document(BytesIO(load_cap_baseline_bytes())), list(doc.tables))


def _body_text(doc) -> str:
    return '\n'.join(paragraph.text for section in doc.sections for paragraph in section.paragraphs)


def _shaded_labels(doc, table) -> list[str]:
    shaded = direct._shaded_fills(doc)
    return [direct._norm(direct._hwp_text(cell)) for row in table.rows for cell in row.cells
            if cell.element.get('borderFillIDRef') in shaded]


def _source_table_of(index: int, repeats: dict) -> int:
    """복제된 서식의 표 번호를 원본서식 표 번호로 되돌린다."""
    position = 0
    for source in range(45):
        for _ in range(repeats.get(source, 1)):
            if position == index:
                return source
            position += 1
    raise AssertionError(index)


def test_hwp_has_same_form_values_as_the_docx_draft(demo_docx):
    doc = _opened(direct.build_hwp_draft(demo_docx))
    compared = 0
    for filled_rows, _, table in _pairs(demo_docx, doc):
        rows = list(table.rows)
        for index, row in enumerate(filled_rows):
            cells = list(rows[index].cells)
            assert len(cells) == len(row)
            for hwp_cell, docx_cell in zip(cells, row):
                assert direct._norm(direct._hwp_text(hwp_cell)) == direct._norm(docx_cell.text)
                compared += 1
    assert compared > 1000
    assert demo.COMPANY == list(doc.tables[12].rows[1].cells)[1].text.strip()


def test_hwp_repeats_forms_for_each_chemical_and_scenario_like_the_docx(demo_docx):
    filled = Document(BytesIO(demo_docx))
    doc = _opened(direct.build_hwp_draft(demo_docx))
    extra = len(filled.tables) - len(Document(BytesIO(load_cap_baseline_bytes())).tables)
    assert extra > 0
    assert len(doc.tables) == 45 + extra
    text = _body_text(doc)
    assert text.count('[별지 제7호서식]') - 1 == sum('취급물질의 일반정보' in t.cell(0, 0).text for t in filled.tables)


def test_hwp_contains_narratives_and_notes_outside_form_tables(demo_docx):
    filled = Document(BytesIO(demo_docx))
    doc = _opened(direct.build_hwp_draft(demo_docx))
    text = direct._norm(_body_text(doc))
    start = next(i for i, p in enumerate(filled.paragraphs) if p.text.startswith(direct.NARRATIVE_START))
    narrative = [p.text for p in filled.paragraphs[start:] if p.text.strip()]
    assert any('AI 초안' in line for line in narrative)
    for line in narrative:
        assert direct._norm(line) in text
    assert '총괄영향범위산출근거' in text


def test_hwp_keeps_every_shaded_label_and_never_writes_into_one(demo_docx):
    source = HwpxDocument.open(direct.SOURCE.read_bytes())
    doc = _opened(direct.build_hwp_draft(demo_docx))
    filled = Document(BytesIO(demo_docx))
    repeats = {16: sum('취급물질의 일반정보' in t.cell(0, 0).text for t in filled.tables)}
    repeats[26] = len(doc.tables) - 45 - (repeats[16] - 1) + 1
    for index, table in enumerate(doc.tables):
        original = source.tables[_source_table_of(index, repeats)]
        assert _shaded_labels(doc, table) == _shaded_labels(source, original)

    target = list(source.tables[12].rows[0].cells)[0]
    with pytest.raises(ValueError, match='명칭 칸'):
        direct._write_cell(target, '값', [target], direct._char_colors(source), direct._shaded_fills(source))


def test_hwp_values_do_not_inherit_the_forms_red_or_blue_blank_cell_ink(demo_docx):
    doc = _opened(direct.build_hwp_draft(demo_docx))
    colors = direct._char_colors(doc)
    email = list(doc.tables[12].rows[15].cells)[3]
    assert email.text.strip()
    assert {colors[run.get('charPrIDRef')] for run in email.element.iter(direct.HP + 'run')} == {direct.BLACK}


def test_hwp_adds_rows_when_the_docx_table_grew(demo_docx):
    """별지 제4호 물질 행(세로 병합)과 제6호 행이 서식 칸 수를 넘어도 값이 빠지지 않는다."""
    filled = Document(BytesIO(demo_docx))
    overview = filled.tables[baseline.FORM_TABLE_INDEX['4'][0]]
    rows = baseline._ensure_facility_chemical_row_capacity(overview, 11)
    last = baseline._unique_cells(rows[-1])
    baseline._write_cell(last[-3], '추가 물질')
    chemicals = filled.tables[baseline.FORM_TABLE_INDEX['6'][0]]
    data_row = deepcopy(chemicals.rows[2]._tr)
    note = chemicals.rows[len(chemicals.rows) - 1]._tr
    for _ in range(6):
        note.addprevious(deepcopy(data_row))
    baseline._write_cell(baseline._unique_cells(chemicals.rows[len(chemicals.rows) - 2])[1], '여섯째 추가 행')
    out = BytesIO()
    filled.save(out)

    doc = _opened(direct.build_hwp_draft(out.getvalue()))
    form4 = ''.join(direct._hwp_text(cell) for row in doc.tables[13].rows for cell in row.cells)
    form6 = list(doc.tables[15].rows)
    assert '추가 물질' in form4
    assert len(form6) == 7 + 6
    assert direct._hwp_text(list(form6[-2].cells)[1]) == '여섯째 추가 행'
    assert direct._hwp_text(list(form6[-1].cells)[0]).startswith('주)')


def test_empty_project_still_gets_the_original_form(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = create_direct_cap_project('가상새솔화학', cap_group='1군')
    data = direct.build_hwp_draft(report_export.build_cap_workspace_draft(project).docx)
    tables, _ = read_document('draft.hwp', data)
    assert len(tables) == 45
    assert tables[12].rows[1][:2] == ['사업장명', '가상새솔화학']
    assert tables[16].rows[0][0] == '취급물질의 일반정보'
