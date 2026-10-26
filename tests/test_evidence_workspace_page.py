import os
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.stage2 import evidence_workspace as ew  # noqa: E402
from engine.stage2.direct_template import create_direct_cap_project  # noqa: E402
from engine.stage2.storage import load_project, save_project  # noqa: E402

SCRIPT = f'''
import runpy
import streamlit as st
st.page_link = lambda *args, **kwargs: None   # 단독 실행 시험에서는 다른 쪽 이동 링크를 만들 수 없음
runpy.run_path({str(ROOT / "ui" / "evidence_workspace_page.py")!r}, run_name="__main__")
'''


class EvidencePageTests(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)   # 프로젝트는 상대 경로(data/runtime)에 저장되므로 임시 폴더에서 실행
        self.project = create_direct_cap_project("가상 사업장", address="서울", cap_group="")
        with ZipFile(BytesIO(ew.demo_zip())) as z:
            for name in z.namelist():
                if name.endswith((".csv", ".xlsx")):
                    ew.ingest(self.project, name, z.read(name), "material" if "materials" in name else "facility")
        save_project(self.project)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def run_page(self):
        at = AppTest.from_string(SCRIPT, default_timeout=60)
        at.session_state["_stage2_active_project_id"] = self.project.project_id
        return at.run()

    def test_first_screen_shows_draft_and_only_exceptions(self):
        at = self.run_page()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        metrics = {m.label: m.value for m in at.metric}
        self.assertEqual(metrics["접수한 문서"], "4")
        self.assertGreater(int(metrics["자동 기입"]), 10)
        self.assertEqual(metrics["확인할 일"], "2")          # 용량 충돌 1 + 수식 값 1
        self.assertEqual([t.label for t in at.tabs], ["1. 자료 올리기", "2. 확인할 일", "3. 시나리오 후보", "4. 연결·내보내기"])

    def test_resolving_a_conflict_from_the_screen_is_saved(self):
        at = self.run_page()
        slot = next(s for s in ew.slots(self.project) if s["status"] == "값 충돌")
        at.checkbox(key=f"chk_{self.project.project_id}_{slot['key']}_{slot['signature']}").set_value(True).run()
        at.button(key=f"ok_{self.project.project_id}_{slot['key']}").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        saved = load_project(self.project.project_id)
        self.assertEqual(ew.confirmed_entities(saved)["facility:TK-01"]["capacity"], 10)
        self.assertEqual(ew.summary(saved)["conflicts"], 0)

    def test_manual_value_for_unreadable_formula_cell_is_confirmed_in_one_step(self):
        at = self.run_page()
        inputs = list(at.text_input)
        position = next(i for i, t in enumerate(inputs) if t.label == "직접 확인한 최대보유량(kg)")
        inputs[position].input("2000")
        inputs[position + 1].input("현장 확인")   # 같은 폼의 ‘확인한 자료·위치·날짜’
        forms = [t for t in inputs if t.label.startswith("직접 확인한")]
        buttons = [b for b in at.button if b.label == "직접 입력으로 확인"]   # 폼마다 하나, 화면 순서대로
        self.assertEqual(len(forms), len(buttons))
        buttons[forms.index(inputs[position])].click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        saved = load_project(self.project.project_id)
        self.assertEqual(ew.confirmed_entities(saved)["facility:RX-01"]["inventory"], 2000)

    def test_scenario_tab_ranks_before_any_manual_approval_and_asks_only_rank_changing_values(self):
        at = self.run_page()
        frames = [d.value for d in at.dataframe]
        ranked = next(f for f in frames if "예비 지표" in f.columns)
        self.assertEqual(list(ranked["순위"])[:2], [1, 1])    # 값이 없는 두 반응기는 임시값으로 공동 1위
        self.assertIn("가정", " ".join(ranked["값 상태"]))
        titles = [e.label for e in at.expander]
        self.assertTrue(any("RX-01" in t and "최대보유량" in t for t in titles))


if __name__ == "__main__":
    unittest.main()
