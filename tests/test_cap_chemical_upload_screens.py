from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2 import cap_chemical_workspace as chem
from tests.test_cap_chemical_upload import HEADER, ROWS, _xlsx
from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests


class FakeUpload:
    name = "list.xlsx"

    def getvalue(self):
        return _xlsx([HEADER, *ROWS])


def fake_file_uploader(*args, **kwargs):
    return FakeUpload()


def record_add(rows, name, sha):
    import streamlit as st

    st.session_state["got"] = [r["제품명"] for r in rows]
    return f"{name} {len(rows)}"


def form6_project():
    import streamlit as st

    if "project" not in st.session_state:
        st.session_state["project"] = CAPForm1EngineTests()._project()
    return st.session_state["project"]


# AppTest는 스크립트 문자열을 시스템 기본 인코딩으로 저장하므로 스크립트에는 한글을 쓰지 않는다(한글은 위 도우미에 둔다).
SCRIPT_HEAD = (
    "import sys\n"
    "sys.path.insert(0, {root!r})\n"
    "import streamlit as st\n"
    "from tests.test_cap_chemical_upload_screens import fake_file_uploader, record_add, form6_project\n"
    "st.file_uploader = fake_file_uploader\n"
)


def _run(body_lines):
    from streamlit.testing.v1 import AppTest

    root = str(Path(__file__).resolve().parents[1])
    script = SCRIPT_HEAD.format(root=root) + "\n".join(body_lines) + "\n"
    return AppTest.from_string(script, default_timeout=90).run()


class PanelScreenTests(unittest.TestCase):
    def test_preview_counts_and_adding_only_the_clean_rows(self):
        at = _run([
            "from ui import chemical_upload_panel",
            "chemical_upload_panel.render('t', existing=(set(), set()), add_rows=record_add)",
        ])
        self.assertFalse(at.exception)
        metrics = {m.label: m.value for m in at.metric}
        self.assertEqual(metrics["추가할 수 있음"], "4")
        self.assertEqual(metrics["추가되지 않음(오류·중복)"], "2")
        at.button(key="t_add").click().run()
        self.assertEqual(at.session_state["got"], ["톨루엔", "염소", "아세톤", "혼합제품"])

    def test_start_panel_receives_the_uploaded_rows_in_its_table(self):
        at = _run(["from ui import cap_start_panel", "cap_start_panel.render(expanded=True)"])
        self.assertFalse(at.exception)
        at.button(key="cap_start_upload_add").click().run()
        self.assertFalse(at.exception)
        seed = at.session_state["cap_start_seed"]
        self.assertEqual([r["제품명"] for r in seed], ["톨루엔", "염소", "아세톤", "혼합제품"])
        self.assertEqual(seed[0]["최대 동시보유량(ton)"], 12.5)
        self.assertEqual(at.session_state["cap_start_gen"], 1)
        self.assertTrue(any("표에 추가했습니다" in s.value for s in at.success))

    def test_form6_identity_step_accepts_an_upload_into_the_project(self):
        at = _run([
            "from unittest.mock import patch",
            "from ui import cap_form6_view",
            "project = form6_project()",
            "with patch('ui.cap_form6_view.save_project'):",
            "    cap_form6_view.render(project)",
        ])
        self.assertFalse(at.exception)
        at.button(key="cap_form06_upload_add").click().run()
        self.assertFalse(at.exception)
        names = [r.get("물질명") for r in chem._rows(at.session_state["project"])[1]]
        self.assertIn("톨루엔", names)
        self.assertIn("아세톤", names)


if __name__ == "__main__":
    unittest.main()
