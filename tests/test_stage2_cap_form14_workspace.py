from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from engine.stage2 import cap_form14_workspace as f14
from engine.stage2 import cap_guideline as guide
from engine.stage2 import cap_impact_workspace as iw
from engine.stage2 import cap_risk_engine as risk
from engine.stage2 import cap_workspace as ws
from tests.test_stage2_cap_impact_workspace import _project_with_targets

ROOT = Path(__file__).resolve().parents[1]


def _ready_project():
    project = _project_with_targets()
    iw.apply_to_forms(project, iw.evaluate(project))
    return project


class Form14WorkspaceTests(unittest.TestCase):
    def test_schema_and_frequencies_follow_the_printed_form(self):
        self.assertTrue(ws.load_form_schema(14)["title"].endswith(guide.form_guidelines()[14].title))
        printed = guide.initiating_event_frequencies()
        self.assertEqual(len(printed), 10)
        for name, frequency, _ in risk.INITIATING_EVENTS:
            self.assertAlmostEqual(printed[name], frequency, places=12)
        self.assertEqual(f14.EVENT_NAMES, tuple(printed))

    def test_scenario_list_comes_from_the_off_site_scenarios(self):
        self.assertEqual(f14.scenario_names(_ready_project()), ["E-1 염소 독성 누출"])

    def test_suggestions_only_cover_what_facility_type_and_pressure_reveal(self):
        project = _ready_project()
        suggested = f14.suggest_counts(project, "E-1 염소 독성 누출")
        self.assertLessEqual(set(suggested), {"고압용기파열", "상압 탱크 파열 및 누출", "입/출하 시설 누출 사고"})
        for event in ("배관파열", "배관누출", "플랜지 등의 가스켓 파손", "펌프/컴프레서 누출"):
            self.assertNotIn(event, suggested)  # P&ID 사실이라 추정하지 않음

    def test_suggestions_never_overwrite_entered_counts(self):
        project = _ready_project()
        [row] = f14.rows(project)
        row["고압용기파열"] = 0
        row["상압 탱크 파열 및 누출"] = 0
        filled = f14.apply_suggestions(project, [row])
        self.assertEqual(filled[0]["고압용기파열"], 0)
        self.assertEqual(filled[0]["상압 탱크 파열 및 누출"], 0)

    def test_frequency_is_the_sum_of_printed_frequency_times_count(self):
        project = _ready_project()
        [row] = f14.rows(project)
        for event in f14.EVENT_NAMES:
            row[event] = 0
        row.update({"고압용기파열": 1, "배관누출": 10, "플랜지 등의 가스켓 파손": 20, "외부화재": 1})
        f14.save(project, [row])
        data = risk.build_cap_form14_data(project)
        self.assertEqual(data.blockers, ())
        [scenario] = data.scenario_rows
        expected = 1e-6 * 1 + 1e-3 * 10 + 1e-3 * 20 + 1e-2 * 1
        self.assertAlmostEqual(float(scenario["시설빈도(/연)"]), expected, places=9)
        self.assertEqual(scenario["개수 산정근거"], f14.BASIS_DEFAULT)

    def test_uncounted_events_are_reported_and_zero_is_a_valid_answer(self):
        project = _ready_project()
        [row] = f14.rows(project)
        f14.save(project, [row])
        self.assertTrue(any("개수" in item for item in f14.needs(project)))

    def test_mitigation_without_evidence_is_not_accepted(self):
        project = _ready_project()
        [row] = f14.rows(project)
        for event in f14.EVENT_NAMES:
            row[event] = 0
        row["수동적 완화장치"] = "방류벽"
        f14.save(project, [row])
        self.assertTrue(any("증빙" in item for item in f14.needs(project)))
        row["안전성확보설비 증빙"] = "P&ID 12번 도면"
        f14.save(project, [row])
        self.assertEqual(f14.needs(project), [])

    def test_engine_relies_on_the_official_form_when_no_approved_source_exists(self):
        project = _ready_project()
        [row] = f14.rows(project)
        for event in f14.EVENT_NAMES:
            row[event] = 0
        f14.save(project, [row])
        with patch.object(risk, "approved_source_is_current", return_value=False):
            self.assertEqual(risk.build_cap_form14_data(project).blockers, ())
        with patch.object(risk, "approved_source_is_current", return_value=False), \
                patch.object(risk, "_frequencies_match_official_form", return_value=False):
            self.assertTrue(risk.build_cap_form14_data(project).blockers)

    def test_option_lists_and_page_are_wired(self):
        self.assertIn("방류벽", f14.PASSIVE_OPTIONS)
        self.assertIn("가스감지기와 자동차단밸브의 연동", f14.ACTIVE_OPTIONS)
        self.assertIn('14: "별지 제14호"', (ROOT / "ui/cap_workspace_page.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
