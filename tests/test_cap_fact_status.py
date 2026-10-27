"""자료 접수 화면의 사실 표: O / 빈칸 / 충돌 / 확인, 대상별 매트릭스, 올리기 전후 변화."""
from __future__ import annotations

import re
import unittest
from io import BytesIO
from zipfile import ZipFile

from docx import Document

from engine.stage2 import cap_fact_status as fs
from engine.stage2 import demo_full_company as d
from engine.stage2 import evidence_workspace as ew
from engine.stage2.direct_template import create_direct_cap_project

DEVELOPER = re.compile(r"facility:|material:|detector:|site:|[0-9a-f]{40,}|\bCSV 행\b")


def _site_doc(rows):
    doc = Document()
    table = doc.add_table(rows=0, cols=2)
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = label, value
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def _row(rows, fact_id):
    return next(r for r in rows if r["_id"] == fact_id)


class EmptyProjectTests(unittest.TestCase):
    def test_every_company_fact_says_which_file_and_item_to_add(self):
        p = create_direct_cap_project("가상", address="가상 주소", cap_group="")
        rows = fs.fact_rows(p)
        blanks = [r for r in rows if r["_company"] and r["_state"] == fs.BLANK]
        self.assertTrue(blanks)
        for row in blanks:
            self.assertTrue(row["고칠 점"], row["사실"])
        representative = _row(rows, "site.representative")
        self.assertIn("사업장 일반정보", representative["고칠 점"])
        self.assertIn("‘대표자’", representative["고칠 점"])
        self.assertEqual(representative["쓰이는 곳"], "별지 제3·16호")
        # 등록할 때 넣은 이름·주소는 파일이 아니어도 채워진 값으로 보여 줍니다
        self.assertEqual(_row(rows, "site.company_name")["_state"], fs.O)
        self.assertEqual(_row(rows, "site.address")["출처"], "파일 아님: 직접 입력한 값")

    def test_derived_values_are_shown_apart(self):
        p = create_direct_cap_project("가상", address="가상 주소", cap_group="")
        derived = [r for r in fs.fact_rows(p) if not r["_company"]]
        self.assertTrue(derived)
        self.assertTrue({r["_state"] for r in derived} <= {fs.DONE, fs.NOT_DONE, fs.BLANK, fs.O, fs.CHECK})
        self.assertEqual(_row(derived, "legal.writing_level")["_state"], fs.NOT_DONE)


class DemoCompanyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        files = d.files()
        cls.p = create_direct_cap_project(d.COMPANY, address=d.DATA["company"]["주소"], cap_group="")
        cls.before = fs.snapshot(cls.p)
        for name in ("01_제품목록.xlsx", "02_설비대장.xlsx", "03_사업장_일반정보.docx", "04_공정설명서.docx",
                     "05_SDS_물성표.xlsx", "06_설비사양_안전설비.xlsx"):
            ew.ingest(cls.p, name, files[name], ew.classify_document(name, files[name]))
        ew.publish(cls.p, replace_existing=True)
        cls.rows = fs.fact_rows(cls.p)

    def test_most_company_facts_are_found_with_their_source(self):
        info = fs.summary(self.rows)
        self.assertEqual(info["conflicts"], 0)
        self.assertEqual(info["blank_required"], 0)
        self.assertGreater(info["filled"], 70)
        row = _row(self.rows, "site.representative")
        self.assertEqual((row["상태"], row["값"]), ("O", d.DATA["company"]["representative"]))
        self.assertIn("03_사업장_일반정보.docx", row["출처"])
        self.assertEqual(_row(self.rows, "facility.connection_size")["값"], "4대 모두")

    def test_matrix_has_a_row_per_facility(self):
        data = fs.matrix(self.p, "facility", required_only=True)
        self.assertEqual(len(data["rows"]), 4)
        self.assertIn("최대 연결구 크기(mm)", data["columns"])
        self.assertTrue(all(row["설비명"] == "O" for row in data["rows"]))
        self.assertEqual(data["problems"], [])
        self.assertEqual(len(fs.matrix(self.p, "detector")["rows"]), 3)

    def test_change_after_upload(self):
        delta = fs.change(self.before, fs.snapshot(self.p))
        self.assertGreater(delta["filled_added"], 100)
        self.assertEqual(delta["conflicts_added"], 0)
        self.assertIn("O가", fs.change_text(delta))

    def test_filters(self):
        only3 = fs.fact_rows(self.p, forms=[3])
        self.assertTrue(only3)
        self.assertTrue(all(3 in r["_forms"] for r in only3))
        self.assertEqual(len(fs.fact_rows(self.p, group="2군")), len(self.rows))   # 별지 1·3~11호는 두 군 모두 필요

    def test_no_developer_text(self):
        for row in self.rows + fs.matrix(self.p, "facility")["rows"] + fs.matrix(self.p, "material")["rows"]:
            for key, value in row.items():
                if not key.startswith("_"):
                    self.assertIsNone(DEVELOPER.search(str(value)), (key, value))


class ConflictTests(unittest.TestCase):
    def test_conflict_between_files_is_never_o(self):
        p = create_direct_cap_project("가상", address="가상 주소", cap_group="")
        ew.ingest(p, "a.docx", _site_doc([("대표자", "홍가상"), ("대표전화", "02-1")]), "site")
        before = fs.snapshot(p)
        ew.ingest(p, "b.docx", _site_doc([("대표자", "김가상"), ("대표전화", "02-1")]), "site")
        row = _row(fs.fact_rows(p), "site.representative")
        self.assertEqual(row["_state"], fs.CONFLICT)
        self.assertEqual(row["상태"], "⚠ 충돌")
        self.assertIn("a.docx", row["고칠 점"])
        self.assertIn("b.docx", row["고칠 점"])
        delta = fs.change(before, fs.snapshot(p))
        self.assertEqual(delta["conflicts_added"], 1)
        self.assertEqual(delta["filled_removed"], 1)
        self.assertIn("새 충돌 1개", fs.change_text(delta))

    def test_file_value_differing_from_registered_value_is_a_conflict(self):
        p = create_direct_cap_project("가상", address="등록한 주소", cap_group="")
        ew.ingest(p, "a.docx", _site_doc([("사업장 주소", "다른 주소"), ("대표자", "홍가상")]), "site")
        ew.publish(p, replace_existing=True)
        self.assertEqual(p.get_field("business.address").value, "등록한 주소")
        self.assertEqual(_row(fs.fact_rows(p), "site.address")["_state"], fs.CONFLICT)

    def test_facility_conflict_shows_in_row_and_matrix(self):
        p = create_direct_cap_project("가상", address="가상 주소", cap_group="")
        with ZipFile(BytesIO(ew.demo_zip())) as z:
            for name in z.namelist():
                if name.endswith((".csv", ".xlsx")):
                    ew.ingest(p, name, z.read(name), ew.classify_document(name, z.read(name)))
        row = _row(fs.fact_rows(p), "facility.capacity")
        self.assertEqual(row["_state"], fs.CONFLICT)
        self.assertIn("TK-01", row["고칠 점"])
        matrix = fs.matrix(p, "facility")
        tank = next(r for r in matrix["rows"] if "TK-01" in r["대상"])
        self.assertEqual(tank["설계용량(m3)"], "⚠ 충돌")
        self.assertTrue(any(problem["항목"] == "설계용량(m3)" for problem in matrix["problems"]))
        unit = _row(fs.fact_rows(p), "facility.inventory")
        self.assertIn(unit["_state"], (fs.CHECK, fs.CONFLICT))      # 수식 칸은 그대로 쓰지 않음


class WhereTests(unittest.TestCase):
    def test_plain_locations(self):
        self.assertEqual(fs.where({"document": "a.csv", "location": "CSV 행 2 열 4"}), "a.csv 2번째 줄")
        self.assertEqual(fs.where({"document": "b.xlsx", "location": "설비 행 3 열 1"}), "b.xlsx ‘설비’ 시트 3번째 줄")
        self.assertEqual(fs.where({"document": "c.docx", "location": "표 1 행 2 열 2"}), "c.docx 표 1 2번째 줄")


if __name__ == "__main__":
    unittest.main()
