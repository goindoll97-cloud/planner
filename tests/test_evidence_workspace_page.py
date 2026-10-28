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
    frame = next(d.value for d in at.dataframe if "고칠 점" in d.value.columns)
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

    def test_questions_step_has_one_correction_table_and_blank_template(self):
        at = self.run_page(step=2)
        self.assertFalse(at.exception)
        self.assertEqual(len(at.dataframe), 1)
        frame = at.dataframe[0].value
        self.assertEqual(list(frame.columns), ["상태", "사실", "쓰이는 곳", "올린 파일", "고칠 점"])
        self.assertTrue(any("03_old_equipment.csv" in str(v) for v in frame["올린 파일"]))
        self.assertNotIn("대상별 표", " ".join(_texts(at)))
        self.assertIn("빈칸 전용 엑셀 양식 내려받기", [b.proto.label for b in at.get("download_button")])

    def test_step_four_lists_narrative_items_and_makes_rule_drafts(self):
        project = load_project(self.pid)
        ew.ingest(project, "plan.docx", _site_doc([("교육 대상", "전 직원")]), "site")
        save_project(project)
        at = self.run_page(4)
        self.assertFalse(at.exception)
        self.assertEqual(len(at.dataframe), 0)
        at.button(key="write_" + self.pid).click().run()
        self.assertFalse(at.exception)
        self.assertIsNotNone(load_project(self.pid).get_field("inventory.facilities"))
        at.button(key="fact_drafts_" + self.pid).click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.get("progress")), 1)
        self.assertEqual(at.get("progress")[0].proto.value, 100)
        self.assertIn("개 완료", at.get("progress")[0].proto.text)

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

    def test_scenarios_show_only_ranked_table_without_detail_menus(self):
        at = self.run_page(3)
        self.assertFalse(at.exception)
        self.assertEqual(len(at.dataframe), 1)
        self.assertIn("설비", at.dataframe[0].value.columns)
        self.assertFalse(any(e.label in ("순서는 어떻게 매기나요?", "조합별로 어떤 값을 썼는지 보기") for e in at.expander))
        self.assertFalse(any(x.key == "combo_" + self.pid for x in at.selectbox))

    def test_write_uses_uploaded_facts_without_confirmation_gate(self):
        at = self.run_page(4)
        at.button(key="write_" + self.pid).click().run()
        self.assertFalse(at.exception)
        self.assertFalse(any("보내기 전 마지막 확인" in s.value for s in at.subheader))
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
        self.assertEqual(list(rows), ["submission"])
        self.assertIn("저장하지 않았어요", rows["submission"]["status"])

    def test_step_four_shows_write_action_and_download_destination(self):
        at = AppTest.from_string(SCRIPT, default_timeout=60)
        at.session_state["_stage2_active_project_id"] = self.pid
        at.session_state["evidence_step_" + self.pid] = 4
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.dataframe), 0)
        at.button(key="write_" + self.pid).click().run()
        self.assertTrue(any("아래에서 내려받으세요" in x.value for x in at.success))
        downloads = [b.proto.label for b in at.get("download_button")]
        self.assertEqual(downloads, ["규정서식 초안 DOCX 내려받기"])
        self.assertFalse(at.error)
        text = " ".join(_texts(at))
        for removed in ("버전관리 열기", "새 사업장은", "서술형 포함 DOCX", "제출 행정서식", "점검하고 내려받기"):
            self.assertNotIn(removed, text)

