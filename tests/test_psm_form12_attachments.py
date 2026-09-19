from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from engine.stage2 import psm_attachments as att
from engine.stage2 import psm_form12_workspace as f12
from engine.stage2 import statutory_report as report
from tests.test_stage2_cap_dispersion import _toxic_project


class Form12Tests(unittest.TestCase):
    def test_known_facts_are_prefilled_and_only_the_rest_is_asked(self):
        project = _toxic_project()
        prefilled = f12.prefilled(project)
        self.assertEqual(prefilled["사업장명"], project.company_name)
        needs = f12.needs(project)
        self.assertNotIn("사업장명", needs)
        self.assertIn("제출구분", needs)
        self.assertIn("근로자수", needs)

    def test_saved_values_win_and_blank_never_erases(self):
        project = _toxic_project()
        f12.save(project, {"제출구분": "기존설비", "근로자수": "40"})
        f12.save(project, {"제출구분": "", "근로자수": "45"})
        self.assertEqual(f12.current(project)["제출구분"], "기존설비")
        self.assertEqual(f12.current(project)["근로자수"], "45")

    def test_invalid_project_type_is_reported(self):
        project = _toxic_project()
        f12.save(project, {"제출구분": "신설"})
        self.assertTrue(any("제출구분" in n for n in f12.needs(project)))

    def test_saved_row_is_what_the_statutory_form_reader_uses(self):
        project = _toxic_project()
        f12.save(project, {"제출구분": "변경", "근로자수": "12"})
        [row] = report._rows(project, f12.KEY)
        self.assertEqual(row["근로자수"], "12")


class AttachmentTests(unittest.TestCase):
    def test_upload_is_held_until_the_content_is_confirmed(self):
        project = _toxic_project()
        with tempfile.TemporaryDirectory() as tmp:
            evidence = att.attach(project, "documents.pid", "pid.pdf", b"%PDF-1.4 x", reference_no="PID-001", root=Path(tmp))
            self.assertEqual(len(evidence.sha256), 64)
            record = project.get_field("documents.pid")
            self.assertEqual(record.status, "HOLD")
            self.assertEqual(att.status(project)[2]["state"], "내용 확인 필요")
            self.assertIn("담당자 확인 필요", report._doc_value(project, "documents.pid"))
            self.assertTrue(att.confirm(project, "documents.pid"))
            self.assertEqual(project.get_field("documents.pid").status, "USER_CONFIRMED")
            self.assertIn("확인완료", report._doc_value(project, "documents.pid"))

    def test_only_listed_slots_and_non_empty_files(self):
        project = _toxic_project()
        with self.assertRaises(ValueError):
            att.attach(project, "psm.other", "a.pdf", b"x")
        with self.assertRaises(ValueError):
            att.attach(project, "documents.pid", "a.pdf", b"")


if __name__ == "__main__":
    unittest.main()
