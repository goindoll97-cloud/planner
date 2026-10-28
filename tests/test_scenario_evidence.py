"""사업장 업무에 올린 시나리오 검토자료가 별지 제12호 표의 빈 칸을 채우는지 시험합니다."""
import unittest

from engine.stage2 import demo_full_company as d, evidence_workspace as ew, scenario_evidence as se
from engine.stage2 import cap_release_workspace as rw
from engine.stage2.direct_template import create_direct_cap_project

FILE = "08_사고시나리오_검토자료.xlsx"


def project(bulk=True):
    p = create_direct_cap_project(d.COMPANY, address=d.company("")["주소"], cap_group="")
    ew.ingest(p, FILE, d.files("")[FILE], "facility")
    if bulk:
        ew.approve_bulk(p)
    return p


class ScenarioEvidenceTests(unittest.TestCase):
    def test_company_values_fill_blank_columns(self):
        p = project()
        got = se.inputs_for(p, "TK-01")
        expected = d.DATA["scenario_inputs"]["TK-01"]
        self.assertEqual(got[rw.HEAD_COLUMN], "3.5")
        self.assertEqual(got[rw.BOUNDARY_COLUMN], "45")
        self.assertEqual(got[rw.HEAT_COLUMN], expected["연소열"].rstrip("0") if "." in expected["연소열"] else expected["연소열"])
        self.assertEqual(se.inputs_for(p, "CY-01")[rw.VAPOR_DENSITY_COLUMN], "6.9")

    def test_user_entered_values_are_never_overwritten(self):
        p = project()
        rows, sources = se.autofill(p, [{"대상 설비번호": "TK-01", rw.HEAD_COLUMN: "9", rw.BOUNDARY_COLUMN: ""}])
        self.assertEqual(rows[0][rw.HEAD_COLUMN], "9")
        self.assertEqual(rows[0][rw.BOUNDARY_COLUMN], "45")
        self.assertNotIn(rw.HEAD_COLUMN, {s["항목"] for s in sources})
        self.assertTrue(all(s["파일"] == FILE for s in sources))

    def test_unconfirmed_values_are_not_used(self):
        p = create_direct_cap_project(d.COMPANY, address=d.company("")["주소"], cap_group="")
        ew.ingest(p, FILE, d.files("")[FILE], "facility")
        ew.slots(p)  # 자동 기입을 통과하지 못한 값은 확인 전까지 쓰지 않습니다
        for slot in ew.slots(p):
            if not slot["chosen"]:
                key = se.COLUMNS.get(slot["field"])
                self.assertNotIn(key, se.inputs_for(p, slot["entity"].split(":", 1)[1]))

    def test_other_equipment_is_untouched(self):
        self.assertEqual(se.inputs_for(project(), "XX-99"), {})


if __name__ == "__main__":
    unittest.main()


class Form14EvidenceTests(unittest.TestCase):
    def test_event_counts_and_mitigation_fill_form14_rows(self):
        from engine.stage2 import cap_form14_workspace as f14, cap_scenario_workspace as sc
        p = project()
        expected = d.DATA["frequency"]["TK-01"]
        got = se.frequency_for(p, "TK-01")
        for event in ("배관누출", "플랜지 등의 가스켓 파손", "상압 탱크 파열 및 누출"):
            self.assertEqual(got[event], expected[event])
        self.assertEqual(got["수동적 완화장치"], expected["수동적 완화장치"])
        self.assertNotIn("능동적 완화장치", got)  # 빈 칸은 만들지 않음
        sc.save_scenarios(p, [{"사고시나리오명": "TK-01 톨루엔 화재", "대상 설비번호": "TK-01"}])
        row = f14.rows(p)[0]
        self.assertEqual(row["배관누출"], expected["배관누출"])
        self.assertEqual(row["안전성확보설비 증빙"], expected["안전성확보설비 증빙"])

    def test_fractional_count_is_not_auto_filled(self):
        p = create_direct_cap_project(d.COMPANY, address=d.company("")["주소"], cap_group="")
        ew.add_manual(p, "facility:TK-09", "event_2", "1.5", "시험")
        self.assertIsNotNone(ew.value_problem("event_2", 1.5))
        self.assertEqual(se.frequency_for(p, "TK-09"), {})


class AutoWriteTests(unittest.TestCase):
    def _with_target(self):
        """승인 DB 없이도 시나리오 대상이 되도록 대상 판정을 고정합니다."""
        from unittest.mock import patch
        from engine.stage2 import cap_scenario_workspace as sc
        p = project()
        target = sc.Target("TK-01", "저장탱크", "가상 톨루엔", sc.FIXED_KIND, "액체", 37000.0, 1000.0, sc.TARGET, "시험")
        return p, patch.object(sc, "evaluate", return_value=[target]), sc

    def test_sync_writes_scenarios_and_frequency_without_a_save_button(self):
        from engine.stage2 import cap_form14_workspace as f14, scenario_autowrite as auto
        p, patcher, sc = self._with_target()
        with patcher, __import__("unittest.mock").mock.patch.object(
                sc, "accident_types", return_value=[sc.FIRE]):
            counts = auto.sync(p)
            rows = sc.saved_scenarios(p)
            self.assertEqual(counts["scenarios"], 1)
            self.assertEqual(rows[0][rw.BOUNDARY_COLUMN], "45")
            self.assertEqual(p.get_field(sc.SCENARIO_KEY).status, "CALCULATED")
            self.assertGreater(counts["frequency"], 0)
            self.assertEqual(f14.rows(p)[0]["배관누출"], d.DATA["frequency"]["TK-01"]["배관누출"])
            self.assertEqual(auto.sync(p), {"scenarios": 0, "frequency": 0, "impact": 0})   # 두 번째는 바뀐 것 없음

    def test_person_saved_values_survive_sync(self):
        from engine.stage2 import scenario_autowrite as auto
        p, patcher, sc = self._with_target()
        with patcher:
            sc.save_scenarios(p, [{"사고시나리오명": "TK-01 직접", "대상 설비번호": "TK-01", rw.BOUNDARY_COLUMN: "7"}])
            auto.sync(p)
            row = sc.saved_scenarios(p)[0]
            self.assertEqual(row[rw.BOUNDARY_COLUMN], "7")
            self.assertEqual(len(sc.saved_scenarios(p)), 1)
