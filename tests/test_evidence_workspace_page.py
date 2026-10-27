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

    def test_reset_all_removes_every_project_but_keeps_other_runtime_data(self):
        from engine.stage2.storage import list_projects
        other = create_direct_cap_project("다른 사업장", address="부산", cap_group="")
        save_project(other)
        keep = Path("data/runtime/law_old_new/keep.txt")
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_text("x")
        at = self.run_page(step=1)
        self.assertTrue(at.button(key="evidence_reset_all").disabled)
        at.checkbox(key="evidence_reset_all_confirm").check().run()
        at.button(key="evidence_reset_all").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(list_projects(), [])
        self.assertTrue(keep.exists())
        self.assertIn("사업장 2곳을 모두 지웠어요", " ".join(_texts(at)))

    def test_full_practice_package_can_be_made_for_a_real_address(self):
        at = self.run_page(step=1)
        self.assertIn("파일 11개", " ".join(b.proto.label for b in at.get("download_button")))
        at.text_input(key="demo_full_address").input("울산광역시 남구 연습로 1").run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        labels = " ".join(b.proto.label for b in at.get("download_button"))
        self.assertIn("파일 10개", labels)
        self.assertIn("실제 지도 조회", " ".join(_texts(at)))

    def test_opens_on_questions_step_with_plain_language_only(self):
        at = self.run_page()
        self.assertEqual(at.radio(key="evidence_step_" + self.pid).value, 2)
        text = " ".join(_texts(at))
        self.assertIn("자료 4개를 읽었어요", text)
        self.assertIn("가상 저장탱크 (TK-01)의 용량이 자료마다 달라요", text)
        self.assertIn("가상 반응기 (RX-01)의 최대보유량 칸에 ‘=1500+500’라고 적혀 있어요", text)
        self.assertIn("엑셀 계산식만 있고 계산 결과가 파일에 저장돼 있지 않아요", text)   # 추측이 아니라 파일에서 확인한 사실
        self.assertEqual(len(at.json), 0)

    def test_no_developer_text_on_any_step(self):
        for step in (1, 2, 3, 4):
            at = self.run_page(step)
            leaked = [t for t in _texts(at) if DEVELOPER_TEXT.search(t)]
            self.assertEqual(leaked, [], f"{step}단계")
            self.assertEqual(len(at.json), 0, f"{step}단계")

    def test_conflict_explains_unit_conversion_and_is_resolved_in_one_click(self):
        at = self.run_page()
        self.assertIn("파일 이름이나 날짜만으로 정하지 마세요", " ".join(_texts(at)))
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
        button = next(b for b in at.button if b.label == "2,000 kg로 저장")
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
        self.assertTrue(at.button(key="final_ok_" + self.pid).disabled)
        for _ in range(10):
            if not any(b.key == "final_ok_" + self.pid for b in at.button):
                break
            source = at.selectbox(key="final_source_" + self.pid).value
            at.checkbox(key="final_check_" + self.pid + "_" + source).set_value(True).run()
            at.button(key="final_ok_" + self.pid).click().run()
        self.assertFalse(ew.unreviewed_legal(load_project(self.pid)))
        at.button(key="publish_" + self.pid).click().run()
        self.assertFalse(at.exception)
        self.assertIsNotNone(load_project(self.pid).get_field("inventory.facilities"))

    def test_more_than_thirty_conflicts_are_reachable(self):
        old = "설비번호,용량(m3)\n" + "".join(f"EX-{i},10\n" for i in range(35))
        new = "설비번호,용량(m3)\n" + "".join(f"EX-{i},12\n" for i in range(35))
        ew.ingest(self.project, "old.csv", old.encode())
        ew.ingest(self.project, "new.csv", new.encode())
        save_project(self.project)
        at = self.run_page(2)
        self.assertTrue(any("전체 36개" in t for t in _texts(at)))
        at.selectbox(key="conflict_page_" + self.pid).set_value(1).run()
        self.assertTrue(any("EX-9의 용량이 자료마다 달라요" in t for t in _texts(at)))

    def test_unread_document_is_visible_in_status(self):
        ew.ingest(self.project, "scan.txt", b"Unstructured text", "facility", "EX")
        save_project(self.project)
        at = self.run_page(2)
        self.assertIn("읽지 못한 파일 1개", " ".join(_texts(at)))


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
            text = " ".join(_texts(at))
            if step == 1:
                self.assertIn("건너뛴 줄: 22번째 줄 ‘합계’ — 번호 칸이 비어 있음", text)
                self.assertIn("글자가 없는 문서예요", text)
                self.assertTrue(any(b.label == "‘함량(wt%)’ 열은" for b in at.selectbox))
            if step == 2:
                # 같은 표기·같은 열은 한 번만 묻고, 원인을 추측하지 않고 걸린 검사만 말합니다
                self.assertIn("물질성상 칸에 ‘액상’이라고 적힌 곳이 29곳 있어요", text)
                self.assertIn("운전압력 칸에 ‘상압’이라고 적힌 곳이 2곳 있어요", text)
                self.assertIn("04_설비목록_2024_구버전.csv의 ‘운전압력’ 열에 단위가 없어요", text)
                self.assertTrue(any(b.label == "33,575 kg로 저장" for b in at.button))
                self.assertNotIn("너무 크거나 작아요", text)

    def test_one_answer_fixes_every_cell_with_the_same_spelling(self):
        at = AppTest.from_string(SCRIPT, default_timeout=120)
        at.session_state["_stage2_active_project_id"] = self.pid
        at.session_state["evidence_step_" + self.pid] = 2
        at.run()
        group = next(g for g in ew.problems(load_project(self.pid)) if g["raw"] == "액상")
        box = next(b for b in at.selectbox if b.label == "‘액상’은 무엇인가요?")
        box.set_value("액체").run()
        save = [b for b in at.button if b.label == "저장"]
        # 화면에서 이 묶음 카드의 저장 버튼을 누름 (같은 키 규칙)
        next(b for b in save if b.key and b.key.startswith("save_") and b.key.endswith(box.key.split("_")[-1])).click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        project = load_project(self.pid)
        states = [s for s in ew.slots(project) if s["field"] == "substance_state" and s["key"] in group["keys"]]
        self.assertEqual(len(states), 29)
        self.assertTrue(all(s["chosen"] and s["chosen"]["value"] == "액체" for s in states))

    def test_unknown_header_is_mapped_once_and_file_is_read_again(self):
        from engine.stage2 import demo_company as dc
        from engine.stage2.storage import save_attachment
        name = "01_제품목록_2026.xlsx"
        save_attachment(self.pid, name, dc.files()[name])
        at = AppTest.from_string(SCRIPT, default_timeout=120)
        at.session_state["_stage2_active_project_id"] = self.pid
        at.session_state["evidence_step_" + self.pid] = 1
        at.run()
        next(b for b in at.selectbox if b.label == "‘함량(wt%)’ 열은").set_value("concentration").run()
        next(b for b in at.button if b.label == "지정하고 다시 읽기" and not b.disabled).click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        project = load_project(self.pid)
        conflicts = {(i["entity"], i["field"]) for i in ew.review_queue(project) if i["kind"] == "충돌"}
        self.assertIn(("material:P-10", "concentration"), conflicts)        # 01(35%)과 개정 MSDS(50%)가 다름이 이제 드러남


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


class ProgressBoardTests(unittest.TestCase):
    """④의 진행 현황판: 화면별 남은 일과, 누르면 다음 서식이 바로 열리는지."""

    def setUp(self):
        from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.project = CAPForm1EngineTests()._project()
        save_project(self.project)
        self.pid = self.project.project_id

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_progress_has_a_draft_download_row_and_a_submission_row(self):
        from ui import cap_common
        info = cap_common.progress(self.project)
        rows = {r["group"]: r for r in info["rows"]}
        self.assertEqual(list(rows), list(cap_common.GROUPS))
        self.assertEqual(list(rows), ["export", "submission"])
        self.assertIn("초안을 내려받을 수 있어요", rows["export"]["status"])
        self.assertIn("저장하지 않았어요", rows["submission"]["status"])

    def test_board_is_shown_in_step_four_and_opens_the_draft_download(self):
        at = AppTest.from_string(SCRIPT, default_timeout=60)
        at.session_state["_stage2_active_project_id"] = self.pid
        at.session_state["evidence_step_" + self.pid] = 4
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        text = " ".join(m.value for m in at.markdown)
        self.assertIn("화학사고예방관리계획서 진행 현황", text)
        self.assertIn("초안 내려받기", text)
        self.assertNotIn("사업장·물질·시설 작성", text)
        page = AppTest.from_file(str(ROOT / "ui" / "cap_export_page.py"), default_timeout=90)
        page.session_state["_stage2_active_project_id"] = self.pid
        page.run()
        self.assertFalse(page.exception, [e.value for e in page.exception])

