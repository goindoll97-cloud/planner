from __future__ import annotations

from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

from engine.stage2 import cap_chemical_upload as up
from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2 import cap_judgement as jd
from tests.test_upload_products_and_mixtures import MIX1, MIX2, SINGLE, _pending, _products

ROOT = Path(__file__).resolve().parents[1]


def _seeded():
    """미리 채워진 물질 하나(예: 염소) + 톨루엔(단일물질) + 세척제A(혼합물, 성분 2개)가 있는 프로젝트."""
    project = _pending()
    up.add_to_project(project, _products([SINGLE, MIX1, MIX2]), file_name="a.xlsx", sha256="abc123456789", sds_confirmed=True)
    return project


class RemoveRowsEngineTests(unittest.TestCase):
    def test_removing_a_row_drops_it_and_keeps_the_others(self):
        project = _seeded()
        before = [r.get("제품명") for r in chem._rows(project)[1]]
        target = before.index("톨루엔") + 1  # 1부터 세는 표시 행 번호

        removed = up.remove_rows(project, [target])

        self.assertEqual(removed, ["톨루엔"])
        after = [r.get("제품명") for r in chem._rows(project)[1]]
        self.assertNotIn("톨루엔", after)
        self.assertEqual(len(after), len(before) - 1)
        self.assertIn("세척제A", after)

    def test_removing_a_mixture_row_also_removes_its_components(self):
        project = _seeded()
        rows = chem._rows(project)[1]
        target = next(n for n, r in enumerate(rows, start=1) if r.get("제품명") == "세척제A")
        self.assertTrue(jd.components_by_row(project).get(target))  # 지우기 전엔 성분이 있다

        up.remove_rows(project, [target])

        self.assertEqual(jd.mixture_components(project), [])

    def test_removing_an_earlier_row_renumbers_the_later_mixtures_components(self):
        project = _seeded()
        rows = chem._rows(project)[1]
        mixture_row = next(n for n, r in enumerate(rows, start=1) if r.get("제품명") == "세척제A")
        earlier_row = mixture_row - 1  # 혼합물 바로 앞 행(톨루엔)을 지운다
        self.assertGreater(earlier_row, 0)

        up.remove_rows(project, [earlier_row])

        after_rows = chem._rows(project)[1]
        new_mixture_row = next(n for n, r in enumerate(after_rows, start=1) if r.get("제품명") == "세척제A")
        self.assertEqual(new_mixture_row, mixture_row - 1)
        components = jd.mixture_components(project)
        self.assertTrue(components)
        self.assertTrue(all(int(float(c["제품목록행번호"])) == new_mixture_row for c in components))

    def test_chemical_inputs_stay_aligned_with_their_own_row_after_a_deletion(self):
        project = _seeded()
        rows = chem._rows(project)[1]
        toluene_row = next(n for n, r in enumerate(rows, start=1) if r.get("제품명") == "톨루엔")
        first_row = 1
        inputs = [{} for _ in rows]
        inputs[toluene_row - 1] = {"함량(%)": "77"}
        jd.save_chemical_inputs(project, inputs)
        self.assertNotEqual(first_row, toluene_row)

        up.remove_rows(project, [first_row])  # 톨루엔보다 앞선 행을 지운다

        after_rows = chem._rows(project)[1]
        new_toluene_row = next(n for n, r in enumerate(after_rows, start=1) if r.get("제품명") == "톨루엔")
        self.assertEqual(jd.chemical_inputs(project)[new_toluene_row - 1]["함량(%)"], "77")

    def test_out_of_range_row_numbers_are_ignored(self):
        project = _seeded()
        before = len(chem._rows(project)[1])
        self.assertEqual(up.remove_rows(project, [999, 0, -1]), [])
        self.assertEqual(len(chem._rows(project)[1]), before)

    def test_removing_every_row_leaves_the_list_empty(self):
        project = _seeded()
        total = len(chem._rows(project)[1])
        up.remove_rows(project, list(range(1, total + 1)))
        self.assertEqual(chem._rows(project)[1], [])


class RemoveRowsScreenTests(unittest.TestCase):
    def _run(self):
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from unittest.mock import patch\n"
            "import streamlit as st\n"
            "from tests.test_chemical_row_delete import _seeded\n"
            "from ui import judgement_project_panel as panel\n"
            "if 'project' not in st.session_state:\n"
            "    st.session_state['project'] = _seeded()\n"
            "with patch('engine.stage2.storage.save_project'):\n"
            "    panel.render(st.session_state['project'])\n"
        ) % str(ROOT)
        return AppTest.from_string(code, default_timeout=60).run()

    def test_the_delete_button_is_disabled_until_a_row_is_checked(self):
        at = self._run()
        self.assertFalse(at.exception)
        button = next(b for b in at.button if b.label == "선택한 물질 삭제")
        self.assertTrue(button.disabled)

    def test_checking_a_row_enables_the_delete_button_and_shows_the_count(self):
        at = self._run()
        project = at.session_state["project"]
        pid = project.project_id
        editor_key = f"judge_chem_rows_{pid}_0"
        self.assertIn(editor_key, at.session_state)

        # st.data_editor는 위젯 상태로 원본 대비 '수정분'(edited_rows)만 받는다: 첫 행의 '삭제' 칸만 체크한다.
        at.session_state[editor_key] = {"edited_rows": {0: {"삭제": True}}, "added_rows": [], "deleted_rows": []}
        at = at.run()
        self.assertFalse(at.exception)

        button = next(b for b in at.button if b.label == "선택한 물질 삭제")
        self.assertFalse(button.disabled)
        self.assertTrue(any(c.value == "1건을 선택했습니다." for c in at.caption))

    def test_checking_a_row_and_clicking_delete_removes_it_and_shows_a_message(self):
        at = self._run()
        project = at.session_state["project"]
        pid = project.project_id
        total = len(chem._rows(project)[1])
        editor_key = f"judge_chem_rows_{pid}_0"

        # AppTest는 새로 run()할 때마다 직접 주입한 위젯 상태를 지운다. 그래서 체크와 클릭을 같은 run()에 함께 반영한다.
        at.session_state[editor_key] = {"edited_rows": {0: {"삭제": True}}, "added_rows": [], "deleted_rows": []}
        button = next(b for b in at.button if b.label == "선택한 물질 삭제")
        button.click()
        at = at.run()

        self.assertFalse(at.exception)
        self.assertTrue(any("물질 1건을 지웠습니다" in s.value for s in at.success))
        self.assertEqual(len(chem._rows(project)[1]), total - 1)


if __name__ == "__main__":
    unittest.main()
