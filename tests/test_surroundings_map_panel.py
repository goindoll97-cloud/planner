from __future__ import annotations

import json
import unittest

from streamlit.testing.v1 import AppTest
from shapely.geometry import mapping

from examples.surroundings_demo import make_demo_project
from engine.stage2 import cap_form8_workspace as f8
from engine.stage2 import cap_surroundings as survey
from ui import surroundings_map_panel as panel


def test_script():
    return '''
import streamlit as st
from unittest.mock import patch
from examples.surroundings_demo import make_demo_project
from ui import surroundings_map_panel as panel
if 'project' not in st.session_state:
    st.session_state['project'] = make_demo_project()
result = {'all_drawings': st.session_state.get('mock_drawings')}
with patch.object(panel, 'st_folium', return_value=result):
    panel.render(st.session_state['project'], persist=lambda project: None, allow_query=False)
'''


class MapPanelTests(unittest.TestCase):
    def test_map_contains_geometry_boundary_draw_tools_and_escaped_names(self):
        project = make_demo_project()
        data = survey.survey(project)
        rows = survey.annotate(project)
        rows[0]['name'] = '<script>alert(1)</script>'
        figure = panel.build_map(data, rows, [mapping(survey.boundary(project))])
        html = figure.get_root().render()
        self.assertIn('L.Control.Draw', html)
        self.assertIn(json.dumps('수집한 지도 객체')[1:-1], html)
        self.assertIn('demo:outside-a', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertEqual(len(data['objects']), 6)

    def test_confirm_group_and_import_through_widgets(self):
        at = AppTest.from_string(test_script()).run(timeout=20)
        self.assertFalse(at.exception)
        checked = next(c for c in at.checkbox if c.label == '시설명과 구성 객체가 같은 시설에 속하는지 확인했습니다')
        checked.check()
        next(b for b in at.button if b.label == '시설 묶음 확인·저장').click().run(timeout=20)
        self.assertFalse(at.exception)
        project = at.session_state['project']
        self.assertEqual(len(survey.saved_groups(project)), 1)
        self.assertEqual(len(survey.saved_groups(project)[0]['members']), 2)
        next(b for b in at.button if b.label == '별지 제8호에 미검토 후보로 추가').click().run(timeout=20)
        self.assertFalse(at.exception)
        project = at.session_state['project']
        self.assertEqual(len(f8.saved_rows(project)), 1)
        self.assertEqual(project.get_field(f8.SITE_KEY).status, 'HOLD')

    def test_deleted_draft_is_distinct_from_no_component_event(self):
        at = AppTest.from_string(test_script()).run(timeout=20)
        project = at.session_state['project']
        original = survey.boundary_record(project)['fingerprint']
        at.session_state['mock_drawings'] = []
        at.run(timeout=20)
        next(c for c in at.checkbox if c.label == '그린 경계가 사업장 부지와 일치하는지 근거자료와 대조했습니다').check()
        next(b for b in at.button if b.label == '사업장 경계 저장·내외부 분석').click().run(timeout=20)
        self.assertFalse(at.exception)
        self.assertTrue(any('경계를 그리거나' in e.value for e in at.error))
        self.assertEqual(survey.boundary_record(at.session_state['project'])['fingerprint'], original)


if __name__ == '__main__':
    unittest.main()
