"""최소 사실 입력형 엑셀(1행 머리글·2행 작성 예시·3행부터 입력, 예시 열 없음)도 그대로 올려 읽는다.

도면·이미지는 사람이 따로 첨부하고 필요한 값만 엑셀에 적는다. 양식 밖 ‘첨부 도면’ 시트는 읽지 않는다.
"""
from io import BytesIO

from docx import Document
from openpyxl import load_workbook

from engine.stage2 import cap_upload_template as tpl, company_workbook_intake as intake, demo_company_workbook as demo
from engine.stage2 import report_export
from engine.stage2.cap_form11_engine import build_cap_form11_data
from engine.stage2.cap_form16_engine import build_cap_form16_data
from engine.stage2.project import Stage2Project

FORM16 = {
    '별지16-5 유관기관': [['관할 소방서', '119'], ['관할 경찰서', '112'], ['가상시 환경과', '000-000-0101']],
    '별지16-6-1 사전정보공유': [['가상 소방서', '취급물질 목록', '공문', '매년 1월']],
    '별지16-6-2 지역사회소통': [['설명회', '가상 마을 주민', '매년 11월', '가상 주민회관', '대면 설명']],
    '별지16-7-1 대피경보': [['인근 사업장', '가상 한빛금속', '전화·문자', '000-000-0201', '이담당']],
    '별지16-7-2 지자체경보전달': [['가상시 북구청', '안전총괄과', '영향범위 내 주민', '재난문자 요청', '000-000-0301']],
    '별지16-8 응급의료': [['1차 의료기관', '가상 새솔의원', '가상시 연습로 10', '000-000-0010', '사내 차량']],
    '별지16-9 대피장소': [['가상 집결지 A', 100, 600, '000-000-0030']],
    '별지16-10 지역사회고지': [['안내문 게시', '가상 마을 주민', '2026-10-15', '행동 요령', '이담당']],
}


def _minimal_workbook() -> bytes:
    """가상 회사 값을 최소입력형 구조로 옮긴 파일: 예시 열 삭제, 2행 예시, 3행부터 입력."""
    converted, issues = intake.inspect(demo.build(), demo.FILENAME, '1군')
    assert issues == []
    book = load_workbook(BytesIO(converted))
    del book[tpl.HELP_SHEET]
    site = book[tpl.SITE_SHEET]
    for row in range(2, site.max_row + 1):
        label = site.cell(row, 1).value
        if label == '화학사고예방관리계획서 접수번호':
            site.cell(row, 2, '해당 없음(신규제출)')
        if label == '화학사고예방관리계획서 결과번호':
            site.cell(row, 2, '해당 없음(신규제출)')
        if label == '대피 장소':
            site.cell(row, 2, None)          # 별지16-9 시트에서 채운다
    for ws in book.worksheets[1:]:
        ws.delete_cols(ws.max_column - 1)            # 예시 열
        ws.insert_rows(2)
        for col in range(1, ws.max_column):
            ws.cell(2, col, ws.cell(3, col).value)   # 예시 행(회사 값 아님)
        ws.cell(2, ws.max_column, '◀ 2행은 작성 예시입니다(회사 값 아님, 지우지 마세요). 실제 값은 3행부터 입력합니다.')
        if ws.title in FORM16:
            ws.delete_rows(3, ws.max_row)
            for r, values in enumerate(FORM16[ws.title], 3):
                for c, value in enumerate(values, 1):
                    ws.cell(r, c, value)
        if ws.title == '가스감지기':
            col = next(c.column for c in ws[1] if c.value == '방폭형 여부')
            for r in range(3, ws.max_row + 1):
                if ws.cell(r, 1).value:
                    ws.cell(r, col, '예')
    drawings = book.create_sheet('첨부 도면')
    drawings.append(['도면 종류', '파일명', '관련 설비번호', '쓰이는 곳', tpl.GUIDANCE_HEADER])
    drawings.append(['확산방지설비 배치도', '예시.pdf', 'TK-01', '별지 제10호', '◀ 2행은 작성 예시입니다.'])
    drawings.append(['확산방지설비 배치도', '실제.pdf', 'TK-01', '별지 제10호', None])
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def test_minimal_layout_reads_from_row_three_and_ignores_the_drawing_sheet():
    converted, issues = intake.inspect(_minimal_workbook(), '최소입력형.xlsx', '1군')
    assert issues == []
    book = load_workbook(BytesIO(converted))
    assert '첨부 도면' not in book.sheetnames
    rows = [r[0] for r in book['설비'].iter_rows(min_row=2, values_only=True) if r[0]]
    assert rows == ['TK-01', 'TK-02', 'RX-01', 'CY-01']     # 2행 예시는 사실이 아니다
    agencies = [r[0] for r in book['별지16-5 유관기관'].iter_rows(min_row=2, values_only=True) if r[0]]
    assert agencies == ['관할 소방서', '관할 경찰서', '가상시 환경과']
    site = {r[0]: r[1] for r in book[tpl.SITE_SHEET].iter_rows(min_row=2, values_only=True)}
    assert site['대피 장소'] == '가상 집결지 A'     # 옮긴 사업장 항목은 별지16 표에서 채운다


def test_minimal_layout_errors_point_at_the_uploaded_cells():
    book = load_workbook(BytesIO(_minimal_workbook()))
    col = next(c.column_letter for c in book['설비'][1] if c.value == '시설유형')
    book['설비'][f'{col}5'] = '반응시설'           # RX-01(3행부터 입력)
    out = BytesIO()
    book.save(out)
    _, issues = intake.inspect(out.getvalue(), '수정본.xlsx', '1군')
    assert [(i['파일·위치'], i['항목']) for i in issues] == [(f'수정본.xlsx · 설비!{col}5', '시설유형')]


def test_form16_tables_numbers_and_explosion_proof_reach_the_forms(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = _minimal_workbook()
    project = intake.project_for_upload(Stage2Project(project_id='MIN', company_name=''), '최소입력형.xlsx', content)
    project.cap_group = '1군'
    intake.apply(project, '최소입력형.xlsx', content)
    assert intake.corrections(project) == []
    assert project.get_field('cap.business.receipt_number').value == '해당 없음(신규제출)'
    assert [r['병원명'] for r in project.get_field('cap.form16.medical').value] == ['가상 새솔의원']
    assert all(r['비고'].startswith('방폭형: 예') for r in build_cap_form11_data(project).rows)
    form16 = build_cap_form16_data(project)
    assert '가상 새솔의원' in dict(form16.external_summary)['응급의료']

    doc = Document(BytesIO(report_export.build_cap_workspace_draft(project).docx))

    def table(first_header):
        return next(t for t in doc.tables if t.rows[0].cells[0].text.strip() == first_header)

    def texts(t, row):
        return [c.text.strip() for c in t.rows[row].cells]

    assert texts(table('관계기관'), 1) == ['관할 소방서', '119', '관할 경찰서', '112']   # 한 행에 두 기관
    assert texts(table('관계기관'), 2)[:2] == ['가상시 환경과', '000-000-0101']
    assert texts(table('대상 기관(협의체)명'), 1) == ['가상 소방서', '취급물질 목록', '공문', '매년 1월']
    assert texts(table('종류'), 1) == ['설명회', '가상 마을 주민', '매년 11월', '가상 주민회관', '대면 설명']
    assert texts(table('지자체ㆍ협의체명'), 1)[0] == '가상시 북구청'
    assert texts(table('대피장소'), 1) == ['가상 집결지 A', '100', '600', '000-000-0030']
    assert texts(table('고지 방법'), 1) == ['안내문 게시', '가상 마을 주민', '2026-10-15']
    hospital = next(t for t in doc.tables if texts(t, 0)[:2] == ['구분', '병원명'])
    assert texts(hospital, 1) == ['1차 의료기관', '가상 새솔의원', '가상시 연습로 10', '000-000-0010']
    form2 = next(t for t in doc.tables if t.rows[0].cells[0].text.strip().startswith('1. 사업장명'))
    assert '해당 없음(신규제출)' in form2.rows[1].cells[1].text
