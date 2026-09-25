from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from engine.stage2.project import Stage2Project
from engine.stage2 import cap_change_tracking as tracking
from engine.stage2 import versioning


class CAPChangeTrackingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _project(self):
        p = Stage2Project(project_id="CAP-DIFF", company_name="한빛화학")
        p.set_field(
            "inventory.chemicals",
            "화학물질",
            [{"물질명": "톨루엔", "CAS 번호": "108-88-3"}],
            "USER_CONFIRMED",
        )
        p.set_field(
            "cap.workspace.facilities",
            "시설",
            [{"설비번호": "TK-101", "설비명": "탱크", "최대보유량(kg)": 10000}],
            "USER_CONFIRMED",
        )
        return p

    def test_summary_detects_added_chemical_facility_and_amount_increase(self):
        p = self._project()
        versioning.freeze_version(p, "CAP", "신규제출", root=self.root)
        p.set_field(
            "inventory.chemicals", "화학물질",
            [
                {"물질명": "톨루엔", "CAS 번호": "108-88-3"},
                {"물질명": "염소", "CAS 번호": "7782-50-5"},
            ],
            "USER_CONFIRMED",
        )
        p.set_field(
            "cap.workspace.facilities", "시설",
            [
                {"설비번호": "TK-101", "설비명": "탱크", "최대보유량(kg)": 15000},
                {"설비번호": "V-201", "설비명": "염소용기", "최대보유량(kg)": 1000},
            ],
            "USER_CONFIRMED",
        )

        original_load = versioning.load_version_fields
        original_diff = versioning.diff_versions
        try:
            versioning.load_version_fields = lambda project_id, version_id, root=versioning.DEFAULT_ROOT: original_load(project_id, version_id, self.root)
            versioning.diff_versions = lambda project, base_version_id, target_version_id=None, root=versioning.DEFAULT_ROOT: original_diff(project, base_version_id, target_version_id, self.root)

            summary = tracking.summarize_changes(p, "CAP-v1.0")
            details = summary.form32_details()
            self.assertIn("염소", details["유해화학물질추가"]["변경 후"])
            self.assertIn("V-201", details["시설추가"]["변경 후"])
            self.assertIn("15 ton", details["취급저장량 증가"]["변경 후"])

            rows = tracking.proposed_form2_rows(p, "CAP-v1.0", change_date="2026-09-21", person="김안전")
            self.assertTrue(rows)
            self.assertTrue(all(row["일자"] == "2026-09-21" for row in rows))
            self.assertTrue(all(row["담당자"] == "김안전" for row in rows))
            self.assertTrue(all(row["후속조치"] == "" for row in rows))
            self.assertNotIn("㈎ 변경제출", [row["후속조치"] for row in rows])
            self.assertIn("㈑ 취급물질 변경", [row["변경의 종류"] for row in rows])
            self.assertIn("", [row["변경의 종류"] for row in rows])
        finally:
            versioning.load_version_fields = original_load
            versioning.diff_versions = original_diff


if __name__ == "__main__":
    unittest.main()
