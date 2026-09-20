from __future__ import annotations

import unittest

from engine.stage2 import cap_workspace as ws
from engine.stage2 import statutory_report as report
from tests import test_stage2_cap_form1_engine as form1_tests


def _project():
    project = form1_tests.CAPForm1EngineTests()._project()
    rows = ws.facility_editor_rows(project)
    rows[0].update({"설비번호": "TK-1", "설비명": "염소 저장탱크", "시설유형": "저장탱크",
                    "물질성상": "액체", "용량": 2500, "용량단위": "L", "비중": 1.4, "취급물질": "염소"})
    ws.save_facility_rows(project, rows)
    return project


class PsmSharedFactsTests(unittest.TestCase):
    def test_psm_form15_reads_the_facilities_entered_for_cap(self):
        rows = report._psm_form15_rows(_project())
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0][0], rows[0][1], rows[0][2]), ("TK-1", "염소 저장탱크", "염소"))
        self.assertEqual(rows[0][3], "저장량 2.5")  # 2500 L -> m3, PSM 제15호 용량명세로 출력

    def test_psm_only_columns_overlay_the_shared_row(self):
        project = _project()
        project.set_field("psm.psi.equipment_specs", "장치 및 설비 명세",
                          [{"설비번호": "TK-1", "본체재질": "SUS304", "용접효율": "0.85"}], "USER_CONFIRMED")
        [row] = report._psm_form15_rows(project)
        self.assertEqual((row[0], row[8], row[11]), ("TK-1", "SUS304", "0.85"))

    def test_without_shared_rows_the_old_path_is_unchanged(self):
        project = form1_tests.CAPForm1EngineTests()._project()
        self.assertEqual(report._psm_facility_rows(project), report._rows(
            project, "psm.psi.equipment_specs", "inventory.facilities", "cap.facility.equipment_specs"))


if __name__ == "__main__":
    unittest.main()
