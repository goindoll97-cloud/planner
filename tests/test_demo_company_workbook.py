from io import BytesIO

from docx import Document
from openpyxl import load_workbook

from engine.stage2 import demo_company_workbook as demo, cap_upload_template as template
from engine.stage2 import company_workbook_intake as intake, cap_fact_drafting, scenario_pipeline, report_export
from engine.stage2.project import Stage2Project



def test_only_one_current_employee_training_download_is_offered():
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "ui" / "evidence_workspace_page.py").read_text(encoding="utf-8")
    assert demo.FILENAME == "화사계_가상회사_작성완료_신입사원용_수정.xlsx"
    assert "화사계_가상회사_작성완료_연습용.xlsx" not in page
    assert page.count("demo_company_workbook.build()") == 1
    assert page.count("key=\"cap_company_demo_template\"") == 1
    assert "가상 회사 정보가 채워진 엑셀 내려받기" in page


def test_training_workbook_layout_reads_back_into_company_schema():
    empty = load_workbook(BytesIO(template.build_company()))
    filled = load_workbook(BytesIO(demo.build()))
    assert filled.properties.identifier == demo.IDENTIFIER
    assert '가상' in filled.properties.description
    assert template.HELP_SHEET not in filled.sheetnames
    assert set(empty.sheetnames) - {template.HELP_SHEET} <= set(filled.sheetnames)
    # 표 시트: 1행 머리글, 2행 작성 요령, 3행 작성 예시, 4행부터 입력
    for ws in filled:
        if ws.cell(1, ws.max_column).value == intake.TRAINING_MARK:
            assert all(ws.cell(3, c).value not in (None, '') for c in range(1, ws.max_column)), ws.title
            assert ws.freeze_panes == 'B4'
    assert all('SDS' not in str(c.value).replace('MSDS', '') for ws in filled
               for row in ws for c in row if c.value is not None)
    assert len([r for r in filled['설비'].iter_rows(min_row=intake.TRAINING_FIRST_ROW) if r[0].value]) == 4
    converted, issues = intake.inspect(demo.build(), demo.FILENAME, '1군')
    assert issues == []
    book = load_workbook(BytesIO(converted))
    assert book.sheetnames == empty.sheetnames
    for ws in book:
        assert [c.value for c in ws[1]] == [c.value for c in empty[ws.title][1]]
    # 예시 행은 사실로 읽지 않는다: 설비 4개, 최대보유량은 설계용량×비중(별표 1)
    rows = [r for r in book['설비'].iter_rows(min_row=2, values_only=True) if r[0]]
    assert [r[0] for r in rows] == ['TK-01', 'TK-02', 'RX-01', 'CY-01']
    inventory = {r[0]: r[8] for r in rows}
    assert inventory == {'TK-01': 435000, 'TK-02': 23400, 'RX-01': 4350, 'CY-01': 1000}



def test_training_excel_dropdowns_only_apply_to_company_input_rows():
    book = load_workbook(BytesIO(demo.build()))
    detector = book["가스감지기"]
    col = next(c.column_letter for c in detector[1] if c.value == "연동여부")
    matches = [v for v in detector.data_validations.dataValidation
               if f"{col}4" in v.sqref]
    assert len(matches) == 1
    assert "예" in matches[0].formula1 and "아니오" in matches[0].formula1
    assert f"{col}3" not in matches[0].sqref  # Example is not an editable fact.

    material = book["물질"]
    tox_col = next(c.column_letter for c in material[1] if c.value == "독성구분")
    assert any("구분 3" in v.formula1 for v in material.data_validations.dataValidation
               if f"{tox_col}4" in v.sqref)


def test_training_workbook_errors_point_at_the_training_file_cells():
    book = load_workbook(BytesIO(demo.build()))
    book['설비']['E6'] = '반응시설'          # RX-01 행(4행부터 입력)
    out = BytesIO()
    book.save(out)
    _, issues = intake.inspect(out.getvalue(), '수정본.xlsx', '1군')
    assert [(i['파일·위치'], i['항목']) for i in issues] == [('수정본.xlsx · 설비!E6', '시설유형')]


def test_training_workbook_without_custom_id_remains_practice_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    book = load_workbook(BytesIO(demo.build()))
    book.properties.identifier = ""
    out = BytesIO()
    book.save(out)
    project = intake.project_for_upload(
        Stage2Project(project_id="SYNTH-START", company_name=""),
        "수정한 연습용 회사.xlsx", out.getvalue(),
    )
    assert project.cap_group == "1군"
    assert not project.stage1_snapshot["legal_applicability_confirmed"]



def test_uploaded_demo_generates_narratives_scenarios_and_docx_without_forging_approval(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    selected = Stage2Project(project_id='EXCEL-START', company_name='')
    project = intake.project_for_upload(selected, demo.FILENAME, demo.build())
    assert project.company_name == demo.COMPANY
    assert project.cap_group == '1군'
    assert not project.stage1_snapshot['legal_applicability_confirmed']
    intake.apply(project, demo.FILENAME, demo.build())
    assert intake.corrections(project) == []
    assert project.get_field('cap.business.representative').value == '김가상'
    assert project.get_field('cap.workspace.dike_rule').value['비율(%)'] == '110'
    assert len(cap_fact_drafting.generate(project)) == 14
    scenarios = scenario_pipeline.refresh(project)
    assert len(scenarios.plan.scenarios) >= 4  # ③에서 경계 확인 후 상세 계산을 진행한다.
    assert any('경계까지 거리' in issue.what for issue in scenarios.problems)
    draft = report_export.build_cap_workspace_draft(project)
    doc = Document(BytesIO(draft.docx))
    text = '\n'.join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells])
    assert demo.COMPANY in text
    assert '김가상' in text
    assert 'TK-01' in text
    assert 'AI 초안' not in text          # 서술형은 프로그램이 바로 확정(승인 단계 없음)
    assert not draft.state.final_ready


def test_reuploading_the_workbook_keeps_map_survey_results(tmp_path, monkeypatch):
    from openpyxl import load_workbook
    from engine.stage2 import evidence_workspace as ew
    monkeypatch.chdir(tmp_path)
    project = intake.project_for_upload(Stage2Project(project_id='EXCEL-START', company_name=''), demo.FILENAME, demo.build())
    intake.apply(project, demo.FILENAME, demo.build())
    project.set_field(ew.SURVEY_KEY, '보호대상', [{'보호대상 명칭': '가상학교'}], 'HOLD')
    rows = project.get_field(ew.SCENARIO_INPUT_KEY).value
    next(r for r in rows if r['설비번호'] == 'TK-01').update({'경계까지 거리(m)': 120, '사고원점 좌표': '35,127'})
    project.set_field(ew.SCENARIO_INPUT_KEY, '시나리오 입력', rows, 'HOLD')
    book = load_workbook(BytesIO(demo.build()))
    book['설비']['B2'] = '가상 톨루엔 저장탱크(수정)'
    out = BytesIO()
    book.save(out)
    assert intake.apply(project, demo.FILENAME, out.getvalue())
    assert [r['보호대상 명칭'] for r in project.get_field(ew.SURVEY_KEY).value] == ['가상학교']
    tk = next(r for r in project.get_field(ew.SCENARIO_INPUT_KEY).value if r['설비번호'] == 'TK-01')
    assert tk['경계까지 거리(m)'] == 120 and tk['사고원점 좌표'] == '35,127'
    assert str(tk['액위(m)']) == '6'       # 회사 엑셀의 시나리오 입력값은 그대로 읽힌다


def test_workbook_emergency_facts_fill_the_form16_summary(tmp_path, monkeypatch):
    from engine.stage2.cap_form16_engine import build_cap_form16_data
    monkeypatch.chdir(tmp_path)
    project = intake.project_for_upload(Stage2Project(project_id='EXCEL-START', company_name=''), demo.FILENAME, demo.build())
    intake.apply(project, demo.FILENAME, demo.build())
    data = build_cap_form16_data(project)
    assert not [b for b in data.company_blockers if '회사 확정자료가 없습니다' in b]
    values = dict(data.internal_summary + data.external_summary)
    assert '박가상' in values['가동중지 권한·절차']
    assert '가상 집결지 A' in values['주민 경보·대피']
