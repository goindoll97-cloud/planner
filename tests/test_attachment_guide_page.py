from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_attachment_guide_is_a_sidebar_page_with_text_only():
    app = (ROOT / 'app.py').read_text(encoding='utf-8')
    assert 'st.Page("ui/attachment_guide_page.py", title="도면·SDS 첨부 안내"' in app

    at = AppTest.from_file(str(ROOT / 'ui/attachment_guide_page.py')).run()
    assert not at.exception
    assert at.title[0].value == '도면·SDS 첨부 안내'
    assert not at.get('file_uploader')
    assert not at.get('download_button')

    table = at.table[0].value
    assert list(table.columns) == ['계획서 위치', '준비할 자료', '파일에서 확인할 내용']
    assert any('별지 제6·7호' in place and 'SDS/MSDS' in file
               for place, file in zip(table['계획서 위치'], table['준비할 자료']))
    for name in ('전체배치도', '공정흐름도(PFD)', '공정배관계장도(P&ID)',
                 '확산방지설비 배치도', '감지기 배치도', '대피경로', 'SDS/MSDS'):
        assert any(name in value for value in table['준비할 자료']), name
