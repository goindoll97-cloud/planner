"""제출 관리의 단계 전환, 기존 저장본 재사용, 문서별 분리를 확인합니다."""
import os
import tempfile
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest
from engine.stage2.storage import save_project, load_project
from engine.stage2 import versioning
from tests.test_version_panel import _project

PAGE = Path(__file__).resolve().parents[1] / 'ui/submission_management_page.py'

class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.chdir, self.cwd)
        p = _project()
        p.cap_selected = p.cap_required = p.scope_confirmed = True
        p.cap_group = '1군'
        save_project(p)

    def page(self):
        at = AppTest.from_file(str(PAGE), default_timeout=90)
        at.session_state['_stage2_active_project_id'] = 'p1'
        return at.run()

    def test_saved_submission_and_baseline_are_reused_across_steps(self):
        at = self.page()
        self.assertFalse(at.exception)
        at.button(key='ver_save_CAP_p1').click().run()
        self.assertEqual(len(versioning.list_versions('p1', 'CAP')), 1)
        self.assertFalse(any(b.key == 'ver_do_restore_CAP_p1' for b in at.button))
        for step in (2, 3, 4):
            at.radio(key='management_step_p1_CAP').set_value(step).run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            self.assertEqual(at.selectbox(key='management_base_p1_CAP').value, 'CAP-v1.0')
            self.assertFalse(any(b.key == 'ver_save_CAP_p1' for b in at.button))
        self.assertEqual(load_project('p1').company_name, '한빛화학')

    def test_compare_does_not_require_saving_a_new_submission(self):
        versioning.freeze_version(load_project('p1'), 'CAP', '신규제출')
        p = load_project('p1')
        p.set_field('facility.reactor.volume', '반응기 용량', 8, 'USER_CONFIRMED')
        save_project(p)
        at = self.page()
        at.radio(key='management_step_p1_CAP').set_value(3).run()
        self.assertFalse(at.exception)
        self.assertTrue(any('변경 1건' in x.value for x in at.markdown))
        self.assertEqual(len(versioning.list_versions('p1', 'CAP')), 1)

    def test_psm_submission_history_and_forms_remain_accessible(self):
        p = load_project('p1')
        p.psm_required = p.psm_selected = True
        save_project(p)
        at = self.page()
        at.radio(key='management_doc_p1').set_value('PSM').run()
        at.button(key='ver_save_PSM_p1').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(versioning.list_versions('p1', 'PSM')), 1)
        self.assertEqual(versioning.list_versions('p1', 'CAP'), [])
        at.radio(key='management_step_p1_PSM').set_value(2).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(at.selectbox(key='management_base_p1_PSM').value, 'PSM-v1.0')
        self.assertTrue(any('심사신청서' in x.value for x in at.markdown))

    def test_legacy_action_opens_the_matching_management_step(self):
        versioning.freeze_version(load_project('p1'), 'CAP', '신규제출')
        at = AppTest.from_file(str(PAGE), default_timeout=90)
        at.session_state['_stage2_active_project_id'] = 'p1'
        at.session_state['cap_goto'] = ('submission', 'implementation')
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.radio(key='management_step_p1_CAP').value, 4)
