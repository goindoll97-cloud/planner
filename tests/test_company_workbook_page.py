import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

from engine.stage2 import company_workbook_intake as intake, evidence_workspace as ew
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.storage import save_project, load_project
from tests.test_company_workbook_intake import workbook

PAGE = Path(__file__).resolve().parents[1] / 'ui/evidence_workspace_page.py'


def script(path, name):
    return f'''
import streamlit as st
import runpy
from pathlib import Path
class Upload:
    name = {name!r}
    def getvalue(self): return Path({str(path)!r}).read_bytes()
original = st.file_uploader
original_link = st.page_link
def upload(*args, **kwargs):
    st.session_state['upload_accepts'] = kwargs
    return Upload()
st.file_uploader = upload
st.page_link = lambda *args, **kwargs: None
try:
    runpy.run_path({str(PAGE)!r}, run_name='__main__')
finally:
    st.file_uploader = original
    st.page_link = original_link
'''


def test_excel_only_page_upload_correction_and_latest_renamed_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = create_direct_cap_project('시험', address='주소', cap_group='')
    save_project(p)
    source = tmp_path / 'source.xlsx'; source.write_bytes(workbook(pressure='압력모름'))
    at = AppTest.from_string(script(source, '작성.xlsx'), default_timeout=90)
    at.session_state['_stage2_active_project_id'] = p.project_id
    at.run()
    assert not at.exception
    accepts = at.session_state['upload_accepts']
    assert accepts['type'] == ['xlsx']
    assert accepts['accept_multiple_files'] is False
    labels = [d.proto.label for d in at.get('download_button')]
    assert labels == ['회사 작성용 엑셀 내려받기 · 전체 항목', '가상 회사 정보가 채워진 엑셀 내려받기']
    at.button(key='read_' + p.project_id).click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert intake.current(load_project(p.project_id))['name'] == '작성.xlsx'
    assert len(at.dataframe) == 1
    frame = at.dataframe[0].value
    assert any('설비!' in v for v in frame['파일·위치'])
    assert any('압력' in v for v in frame['항목'])
    assert '김대표' == load_project(p.project_id).get_field('cap.business.representative').value
    at.button(key='replace_excel_' + p.project_id).click().run()
    assert at.radio(key='evidence_step_' + p.project_id).value == 1
    source.write_bytes(workbook('이대표', include_tank=False))
    updated = AppTest.from_string(script(source, '수정본.xlsx'), default_timeout=90)
    updated.session_state['_stage2_active_project_id'] = p.project_id
    updated.session_state['evidence_step_' + p.project_id] = 1
    updated.run().button(key='read_' + p.project_id).click().run()
    assert not updated.exception
    saved = load_project(p.project_id)
    assert intake.current(saved)['name'] == '수정본.xlsx'
    assert saved.get_field('cap.business.representative').value == '이대표'
    assert not any(f['entity'] == 'facility:TK-01' for f in ew.graph_facts(saved))
    assert not any('압력' in v for v in updated.dataframe[0].value['항목'])


def test_failed_new_upload_keeps_previous_and_shows_error_table(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = create_direct_cap_project('시험', address='주소', cap_group='')
    intake.apply(p, '정상.xlsx', workbook()); save_project(p)
    source = tmp_path / 'bad.xlsx'; source.write_bytes(b'invalid')
    at = AppTest.from_string(script(source, '손상.xlsx'), default_timeout=90)
    at.session_state['_stage2_active_project_id'] = p.project_id
    at.session_state['evidence_step_' + p.project_id] = 1
    at.run().button(key='read_' + p.project_id).click().run()
    assert not at.exception
    assert at.error
    assert len(at.dataframe) == 1
    assert intake.current(load_project(p.project_id))['name'] == '정상.xlsx'
    assert any('정상.xlsx' in c.value for c in at.caption)


def test_first_demo_upload_creates_workplace_without_registration_corner(tmp_path, monkeypatch):
    from engine.stage2 import demo_company_workbook as demo
    from engine.stage2.storage import list_projects
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'demo.xlsx'; source.write_bytes(demo.build())
    at = AppTest.from_string(script(source, demo.FILENAME), default_timeout=90).run()
    assert not at.exception
    assert not list_projects()
    assert not any(e.label == '새 사업장 만들기' for e in at.expander)
    assert not at.text_input
    assert any(d.proto.label == '가상 회사 정보가 채워진 엑셀 내려받기' for d in at.get('download_button'))
    at.button(key='read_EXCEL-START').click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(list_projects()) == 1
    p = load_project(at.session_state['_stage2_active_project_id'])
    assert p.company_name == demo.COMPANY
    assert p.cap_group == '1군'
    assert not p.stage1_snapshot['legal_applicability_confirmed']
    assert p.get_field('cap.business.representative').value == '김가상'
    at.radio(key='evidence_step_' + p.project_id).set_value(4).run()
    assert not at.exception
    assert '규정서식 초안 DOCX 내려받기' in [b.proto.label for b in at.get('download_button')]


def test_demo_upload_from_other_workplace_does_not_replace_its_data(tmp_path, monkeypatch):
    from engine.stage2 import demo_company_workbook as demo
    from engine.stage2.storage import list_projects
    monkeypatch.chdir(tmp_path)
    p = create_direct_cap_project('시험', cap_group='')
    intake.apply(p, '원본.xlsx', workbook()); save_project(p)
    before = load_project(p.project_id).to_dict()
    source = tmp_path / 'demo.xlsx'; source.write_bytes(demo.build())
    at = AppTest.from_string(script(source, demo.FILENAME), default_timeout=90)
    at.session_state['_stage2_active_project_id'] = p.project_id
    at.session_state['evidence_step_' + p.project_id] = 1
    at.run().button(key='read_' + p.project_id).click().run()
    assert not at.exception
    assert len(list_projects()) == 2
    assert load_project(p.project_id).company_name == before['company_name']
    assert load_project(p.project_id).get_field('cap.business.representative').value == '김대표'
    active = load_project(at.session_state['_stage2_active_project_id'])
    assert active.company_name == demo.COMPANY
