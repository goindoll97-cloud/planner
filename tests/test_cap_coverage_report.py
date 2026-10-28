from __future__ import annotations

import unittest
from unittest.mock import patch

from engine.stage2 import cap_coverage_report as report
from engine.stage2 import demo_company
from engine.stage2 import evidence_workspace as ew


def _project():
    from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests

    return CAPForm1EngineTests()._project()


class FileResultTests(unittest.TestCase):
    def setUp(self):
        self.project = _project()

    def _ingest(self, name, content, kind="facility"):
        with patch("engine.stage2.storage.save_project"):
            ew.ingest(self.project, name, content, kind)

    def test_clean_table_is_read(self):
        self._ingest("eq.csv", "설비번호,설비명,용량(m3)\nTK-01,탱크,10\n".encode("utf-8"))
        rows = report.file_results(self.project)
        self.assertEqual([r["읽은 결과"] for r in rows if r["파일"] == "eq.csv"], [report.READ_OK])
        self.assertTrue(rows[0]["읽어서 채운 값"] > 0)

    def test_scanned_pdf_is_reported_as_unreadable_with_a_fix(self):
        self._ingest("scan.pdf", demo_company._scanned_pdf())
        row = next(r for r in report.file_results(self.project) if r["파일"] == "scan.pdf")
        self.assertEqual(row["읽은 결과"], report.READ_FAILED)
        self.assertIn("스캔본", row["읽지 못한 이유"])
        self.assertTrue(row["고치는 방법"])

    def test_text_without_any_linkable_value_is_reported(self):
        self._ingest("memo.txt", "안전하게 관리하고 있습니다.".encode("utf-8"))
        row = next(r for r in report.file_results(self.project) if r["파일"] == "memo.txt")
        self.assertEqual(row["읽은 결과"], report.READ_NOT_LINKED)
        self.assertEqual(row["읽어서 채운 값"], 0)


class ItemStatusTests(unittest.TestCase):
    def test_items_are_grouped_by_form_and_separate_missing_from_computed(self):
        project = _project()
        rows = report.item_status(project)
        self.assertTrue(rows)
        self.assertEqual([r["_form"] for r in rows], sorted(r["_form"] for r in rows))
        statuses = {r["현황"] for r in rows}
        self.assertIn(report.FILLED, statuses)
        self.assertIn(report.MISSING, statuses)       # 올린 파일이 없으면 ‘읽지 못했을 수 있음’이 아니라 ‘자료에 없음’
        self.assertNotIn(report.POSSIBLY_UNREAD, statuses)
        for row in rows:
            if row["현황"] == report.MISSING:
                self.assertTrue(row["필요한 자료"])      # 무엇을 올려야 하는지 항상 알려 준다

    def test_missing_becomes_possibly_unread_when_a_file_could_not_be_read(self):
        project = _project()
        unread = [{"파일": "scan.pdf", "_ok": False}]
        with patch.object(report, "file_results", return_value=unread):
            rows = report.item_status(project)
        self.assertNotIn(report.MISSING, {r["현황"] for r in rows})
        self.assertIn(report.POSSIBLY_UNREAD, {r["현황"] for r in rows})
        self.assertTrue(all("scan.pdf" in r["비고"] for r in rows if r["현황"] == report.POSSIBLY_UNREAD))

    def test_summary_counts_match_items(self):
        data = report.summary(_project())
        self.assertEqual(sum(data["counts"].values()), data["total"])


if __name__ == "__main__":
    unittest.main()
