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
def _site_doc(rows):
    from docx import Document
    doc = Document()
    table = doc.add_table(rows=0, cols=2)
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = label, value
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


DEVELOPER_TEXT = re.compile(r"[0-9a-f]{40,}|facility:|material:|SHA256|\bCSV 행\b")


def _correction_table(at):
    """② 화면의 ‘파일별 수정 요청’ 표를 글자 하나로."""
    frame = next(d.value for d in at.dataframe if "수정 요청" in d.value.columns)
    return " ".join(" | ".join(str(v) for v in row) for row in frame.itertuples(index=False))


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

    def test_single_combined_practice_package_is_available(self):
        at = self.run_page(step=1)
        labels = " ".join(b.proto.label for b in at.get("download_button"))
        self.assertIn("실제와 비슷한 큰 가상자료 받기", labels)
        self.assertIn("전체 준비자료 목록 한글(HWP)", labels)

    def test_opens_on_questions_step_with_plain_language_only(self):
        at = self.run_page()
        self.assertEqual(at.radio(key="evidence_step_" + self.pid).value, 2)
        text = " ".join(_texts(at))
        self.assertIn("자료 4개를 읽었어요", text)
        self.assertNotIn("직접 확인·입력", text)                 # 화면에서 값을 대신 고르거나 적는 길은 두지 않음
        requests = _correction_table(at)
        self.assertIn("가상 저장탱크 (TK-01) · 용량", requests)
        self.assertIn("‘=1500+500’: 엑셀 계산식만 있고 계산 결과가 파일에 저장돼 있지 않아요", requests)   # 파일에서 확인한 사실
        self.assertEqual(len(at.json), 0)

    def test_remove_file_button_drops_its_values(self):
        at = self.run_page(step=1)
        name = "03_old_equipment.csv"
        sha = next(d["sha256"] for d in ew.documents(self.project) if d["name"] == name)
        at.button(key=f"remove_{self.pid}_{sha[:12]}").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        project = load_project(self.pid)
        self.assertNotIn(name, [d["name"] for d in ew.documents(project)])
        self.assertEqual(ew.confirmed_entities(project)["facility:TK-01"]["capacity"], 10)   # 충돌하던 값이 빠져 바로 정해짐

    def test_questions_step_shows_fact_table_with_filters_and_matrix(self):
        at = self.run_page(step=2)
        text = " ".join(_texts(at))
        self.assertIn("화학사고예방관리계획서에 필요한 사실", text)
        self.assertIn("대상별 표", text)
        labels = [m.label for m in at.metric]
        self.assertIn("파일에서 찾은 사실", labels)
        self.assertIn("충돌", labels)
        conflicts = next(m for m in at.metric if m.label == "충돌")
        self.assertNotEqual(str(conflicts.value), "0")              # 연습 자료의 TK-01 용량 충돌
        at.radio(key="fact_view_" + self.pid).set_value("전체").run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        at.radio(key="fact_group_" + self.pid).set_value("1군").run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        labels = " ".join(b.proto.label for b in at.get("download_button"))
        self.assertIn("엑셀 업로드 양식 내려받기 (빈 사실", labels)
        at.checkbox(key="template_full_" + self.pid).check().run()
        self.assertIn("(모든 사실)", " ".join(b.proto.label for b in at.get("download_button")))

    def test_step_four_lists_narrative_items_and_makes_rule_drafts(self):
        from engine.stage2 import cap_fact_drafting as fd
        project = load_project(self.pid)
        ew.ingest(project, "plan.docx", _site_doc([("교육 대상", "전 직원"), ("대표자", "홍가상")]), "site")
        save_project(project)
        at = self.run_page(step=4)
        self.assertIn("서술형 항목", " ".join(_texts(at)))
        saved = load_project(self.pid)
        training = next(i for i in fd.items(saved) if i.key == "cap.prevention.training")
        self.assertEqual(training.state, fd.HAS_DRAFT)              # 화면을 열면 근거 사실로 규칙 초안을 만들어 둠
        self.assertIn("[확인 필요: 교육 주기]", training.draft)
        at.button(key="fact_drafts_" + self.pid).click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertIn("서술형 초안", " ".join(_texts(at)))

    def test_upload_change_message_is_shown_once(self):
        at = AppTest.from_string(SCRIPT, default_timeout=60)
        at.session_state["_stage2_active_project_id"] = self.pid
        at.session_state["evidence_change"] = "이번에 올린 파일로 O가 3개 늘었고 새 충돌 1개."
        at.run()
        self.assertTrue(any("O가 3개 늘었고" in str(w.value) for w in at.warning))
        at.run()
        self.assertFalse(any("O가 3개 늘었고" in str(w.value) for w in at.warning))

    def test_no_developer_text_on_any_step(self):
        for step in (1, 2, 3, 4):
            at = self.run_page(step)
            leaked = [t for t in _texts(at) if DEVELOPER_TEXT.search(t)]
            self.assertEqual(leaked, [], f"{step}단계")
            self.assertEqual(len(at.json), 0, f"{step}단계")

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
                # 같은 표기·같은 열은 한 줄로 모으고, 원인을 추측하지 않고 걸린 검사와 파일 위치만 말합니다
                requests = _correction_table(at)
                self.assertIn("‘액상’: 선택지에 없는 말이에요", requests)
                self.assertIn("‘상압’: 숫자가 아니에요", requests)
                self.assertIn("04_설비목록_2024_구버전.csv", requests)
                self.assertIn("항목 이름에 단위가 없어요", requests)
                self.assertNotIn("너무 크거나 작아요", requests)

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

