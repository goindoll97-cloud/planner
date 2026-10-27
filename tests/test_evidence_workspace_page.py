import os
import re
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

PAGE = ROOT / "ui" / "evidence_workspace_page.py"
SCRIPT = f'''
import runpy
import streamlit as st
_saved = st.page_link
st.page_link = lambda *args, **kwargs: None   # 단독 실행 시험에서는 다른 쪽 이동 링크를 만들 수 없음
try:
    runpy.run_path({str(PAGE)!r}, run_name="__main__")
finally:
    st.page_link = _saved
'''
DEVELOPER_TEXT = re.compile(r"[0-9a-f]{40,}|facility:|material:|SHA256|\bCSV 행\b")


def _texts(at):
    out = []
    for kind in ("markdown", "caption", "subheader", "title", "info", "warning", "success", "error"):
        out.extend(str(e.value) for e in getattr(at, kind))
    return out


class EvidencePageTests(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)   # 프로젝트는 상대 경로(data/runtime)에 저장되므로 임시 폴더에서 실행
        self.project = create_direct_cap_project("가상 사업장", address="서울", cap_group="")
        with ZipFile(BytesIO(ew.demo_zip())) as z:
            for name in z.namelist():
                if name.endswith((".csv", ".xlsx")):
                    ew.ingest(self.project, name, z.read(name), ew.classify_document(name, z.read(name)))
        save_project(self.project)
        self.pid = self.project.project_id

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def run_page(self, step=None):
        at = AppTest.from_string(SCRIPT, default_timeout=60)
        at.session_state["_stage2_active_project_id"] = self.pid
        if step:
            at.session_state["evidence_step_" + self.pid] = step
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def saved(self):
        return ew.confirmed_entities(load_project(self.pid))

    def test_opens_on_questions_step_with_plain_language_only(self):
        at = self.run_page()
        self.assertEqual(at.radio(key="evidence_step_" + self.pid).value, 2)
        text = " ".join(_texts(at))
        self.assertIn("자료 4개를 읽었어요", text)
        self.assertIn("가상 저장탱크 (TK-01)의 용량이 자료마다 달라요", text)
        self.assertIn("엑셀 계산식(`=1500+500`)", text)
        self.assertEqual(len(at.json), 0)

    def test_no_developer_text_on_any_step(self):
        for step in (1, 2, 3, 4):
            at = self.run_page(step)
            leaked = [t for t in _texts(at) if DEVELOPER_TEXT.search(t)]
            self.assertEqual(leaked, [], f"{step}단계")
            self.assertEqual(len(at.json), 0, f"{step}단계")

    def test_conflict_explains_unit_conversion_and_is_resolved_in_one_click(self):
        at = self.run_page()
        slot = next(s for s in ew.slots(self.project) if s["status"] == "값 충돌")
        radio = at.radio(key=f"pick_{self.pid}_{slot['key']}")
        self.assertIn("10 m³ — 02_equipment.csv 2번째 줄 (자료에는 ‘10,000 L’로 적혀 있음)", radio.options)   # 화면에 보이는 문구
        ten = next(f["id"] for f in slot["facts"] if f["value"] == 10)
        radio.set_value(ten).run()
        at.button(key=f"ok_{self.pid}_{slot['key']}").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(self.saved()["facility:TK-01"]["capacity"], 10)

    def test_formula_cell_offers_computed_value(self):
        at = self.run_page()
        button = at.button(key=f"formula_{self.pid}_facility:RX-01|inventory")
        self.assertIn("2,000 kg", button.label)
        button.click().run()
        self.assertFalse(at.exception)
        self.assertEqual(self.saved()["facility:RX-01"]["inventory"], 2000)

    def test_rank_changing_missing_value_is_asked_once(self):
        at = self.run_page()
        text = " ".join(_texts(at))
        self.assertEqual(text.count("가상 예비 반응기 (RX-02)의 최대보유량이 자료에 없어요"), 1)
        # 같은 값을 ‘자료에 없는 정보’에서 다시 묻지 않음
        self.assertFalse(any(t.label.startswith("최대보유량") and "missing_" in (t.key or "") for t in at.text_input))
        at.text_input(key=f"rank_{self.pid}_facility:RX-02_inventory_in").input("3000").run()
        at.button(key=f"rank_{self.pid}_facility:RX-02_inventory_ok").click().run()
        self.assertEqual(self.saved()["facility:RX-02"]["inventory"], 3000)

    def test_missing_information_uses_choices_not_internal_ids(self):
        at = self.run_page()
        box = at.selectbox(key=f"missing_{self.pid}_facility:TK-01_facility_type")
        self.assertIn("저장탱크", box.options)
        box.set_value("저장탱크").run()
        submit = next(b for b in at.button if b.label == "저장" and "facility:TK-01" in str(b.form_id or ""))
        submit.click().run()
        self.assertEqual(self.saved()["facility:TK-01"]["facility_type"], "저장탱크")

    def test_scenarios_rank_before_answers_and_explain_values_in_words(self):
        at = self.run_page(3)
        ranked = next(d.value for d in at.dataframe if "순서" in d.value.columns)
        self.assertEqual(list(ranked["순서"])[:2], [1, 1])    # 값이 없는 두 반응기는 임시값으로 공동 1위
        self.assertIn("값이 더 필요해요", " ".join(ranked["상태"]))
        self.assertTrue(any("자료에 없어 임시로 넣은 값" in m.value for m in at.markdown))

    def test_export_requires_one_final_check_then_sends(self):
        project = load_project(self.pid)
        slot = next(s for s in ew.slots(project) if s["status"] == "값 충돌")
        ew.approve(project, slot["key"], slot["facts"][0]["id"])
        save_project(project)
        at = self.run_page(4)
        self.assertTrue(any("보내기 전 마지막 확인" in s.value for s in at.subheader))
        at.button(key="final_ok_" + self.pid).click().run()
        self.assertFalse(ew.unreviewed_legal(load_project(self.pid)))
        at.button(key="publish_" + self.pid).click().run()
        self.assertFalse(at.exception)
        self.assertIsNotNone(load_project(self.pid).get_field("inventory.facilities"))


class LargeDemoPageTests(unittest.TestCase):
    def setUp(self):
        from engine.stage2 import demo_company as dc
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        project = create_direct_cap_project("가상 한별정밀화학", address="서울", cap_group="")
        for name, content in dc.files().items():
            kind, hint = dc.UPLOAD[name]
            ew.ingest(project, name, content, kind, hint)
        save_project(project)
        self.pid = project.project_id

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_every_step_renders_large_company_in_plain_language(self):
        for step in (1, 2, 3, 4):
            at = AppTest.from_string(SCRIPT, default_timeout=120)
            at.session_state["_stage2_active_project_id"] = self.pid
            at.session_state["evidence_step_" + self.pid] = step
            at.run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            leaked = [t for t in _texts(at) if DEVELOPER_TEXT.search(t)]
            self.assertEqual(leaked, [], f"{step}단계")
            if step == 2:
                text = " ".join(_texts(at))
                self.assertIn("엑셀 계산식(`=50*0.79*1000*0.85`)", text)
                self.assertIn("가상 과산화수소 (P-10)의 함량이 자료마다 달라요", text)
                self.assertIn("상압", text)
                self.assertTrue(any("33,575 kg" in b.label for b in at.button))


class FormulaTests(unittest.TestCase):
    def test_only_plain_arithmetic_is_evaluated(self):
        sys.path.insert(0, str(ROOT))
        import importlib.util
        source = PAGE.read_text(encoding="utf-8")
        start, end = source.index("_SAFE_OPS ="), source.index("class Names")
        namespace = {}
        exec("import ast, operator, re\n" + source[start:end], namespace)
        formula = namespace["_formula_result"]
        self.assertEqual(formula("=1500+500"), 2000)
        self.assertEqual(formula("=2*(1,000+500)"), 3000)
        self.assertIsNone(formula("=A1+B2"))
        self.assertIsNone(formula("=__import__('os')"))
        self.assertIsNone(formula("=1/0"))
        self.assertIsNotNone(importlib.util)


if __name__ == "__main__":
    unittest.main()
