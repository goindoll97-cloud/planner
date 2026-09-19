from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2 import cap_form14_workspace as f14
from engine.stage2 import cap_form15_workspace as f15
from engine.stage2 import cap_guideline as guide
from engine.stage2 import cap_impact_workspace as iw
from engine.stage2 import cap_risk_engine as risk
from engine.stage2 import cap_workspace as ws
from tests.test_stage2_cap_impact_workspace import _project_with_targets

ROOT = Path(__file__).resolve().parents[1]


def _project(counts=None, mitigation=None):
    project = _project_with_targets()
    project.set_field("cap.business.industrial_complex", "산업단지", "해당 없음", "USER_CONFIRMED")
    iw.apply_to_forms(project, iw.evaluate(project))
    [row] = f14.rows(project)
    for event in f14.EVENT_NAMES:
        row[event] = 0
    row.update(counts or {})
    row.update(mitigation or {})
    f14.save(project, [row])
    return project


class ThresholdsAgainstAnnex3Tests(unittest.TestCase):
    def test_engine_thresholds_equal_the_annex_3_table(self):
        self.assertEqual({k: tuple(v) for k, v in risk.APPENDIX3_THRESHOLDS.items()},
                         {k: tuple(v) for k, v in guide.risk_score_thresholds().items()})

    def test_engine_grade_rule_agrees_with_every_legible_cell_of_the_decision_table(self):
        cells = guide.risk_matrix_legible_cells()
        self.assertGreaterEqual(len(cells), 7)
        for (impact, frequency), grade in cells.items():
            self.assertEqual(risk._pre_adjustment_grade(impact + frequency), grade, (impact, frequency))


class Form15WorkspaceTests(unittest.TestCase):
    def test_schema_follows_guideline(self):
        self.assertTrue(ws.load_form_schema(15)["title"].endswith(guide.form_guidelines()[15].title))

    def test_scores_are_calculated_from_forms_12_and_14(self):
        result = f15.analysis(_project(counts={"배관누출": 20, "외부화재": 1}))
        self.assertEqual(result.blockers, ())
        self.assertEqual(result.totals["사고시나리오 총 개수(A)"], 1)
        self.assertAlmostEqual(result.totals["사고시나리오 시설빈도의 합(B)"], 20 * 1e-3 + 1e-2)
        self.assertEqual(result.scores["사고시나리오 개수 구간점수"], 0)
        self.assertEqual(result.scores["시설빈도 구간점수"], 0)   # 0.03/년 < 0.1
        self.assertIn(result.scores["증감 전 위험도"], ("가", "나", "다"))
        self.assertEqual(result.scores["최종 위험도"], "안전원 최종결정 전")

    def test_industrial_complex_excludes_workers_from_the_population(self):
        plain = f15.analysis(_project(counts={"배관누출": 1}))
        project = _project(counts={"배관누출": 1})
        project.set_field("cap.business.industrial_complex", "산업단지", "울산미포국가산업단지", "USER_CONFIRMED")
        park = f15.analysis(project)
        self.assertLess(park.totals["주민수 합(D)"], plain.totals["주민수 합(D)"])

    def test_increase_factors_come_from_protected_targets_in_the_overall_range(self):
        project = _project()
        adj = f15.adjustment(project)
        categories = {t["보호대상 구분"] for t in project.get_field(f15.TARGETS_KEY).value}
        self.assertEqual(adj.increase, int("갑종" in categories) + int("환경수용체" in categories))
        self.assertGreaterEqual(adj.increase, 1)
        self.assertTrue(any("갑종" in r for r in adj.reasons))

    def test_only_mitigations_with_evidence_reduce_the_score(self):
        without = f15.adjustment(_project(mitigation={"수동적 완화장치": "방류벽", "능동적 완화장치": "고정식소화설비"}))
        self.assertEqual(without.decrease, 0)
        with_evidence = f15.adjustment(_project(mitigation={
            "수동적 완화장치": "방류벽", "능동적 완화장치": "고정식소화설비, 예비펌프", "안전성확보설비 증빙": "P&ID 12"}))
        self.assertEqual(with_evidence.decrease, 2)   # 3개여도 최대 -2
        self.assertEqual(len(with_evidence.counted_mitigations), 3)

    def test_reference_grade_moves_at_most_one_level(self):
        self.assertEqual(f15.reference_grade(6, -2, "나"), ("다", 4))
        self.assertEqual(f15.reference_grade(3, 2, "다"), ("다", 5))
        self.assertEqual(f15.reference_grade(4, 2, "다"), ("나", 6))
        self.assertEqual(f15.reference_grade(4, 2, "다")[0], "나")
        # 10점 경계: 9점에 +2 → 점수 11이지만 나에서 가로 한 단계만
        self.assertEqual(f15.reference_grade(9, 2, "나"), ("가", 11))
        # 점수상 두 단계(다→가)가 나오는 경우는 한 단계로 제한
        self.assertEqual(f15.reference_grade(5, 2, "다")[0], "나")
        self.assertEqual(f15.reference_grade(8, 2, "나")[0], "가")

    def test_no_offsite_scenario_means_grade_da_without_analysis(self):
        project = _project_with_targets()
        scenarios = __import__("engine.stage2.cap_scenario_workspace", fromlist=["x"]).saved_scenarios(project)
        scenarios[0]["경계까지 거리(m)"] = "1000000"
        __import__("engine.stage2.cap_scenario_workspace", fromlist=["x"]).save_scenarios(project, scenarios)
        iw.apply_to_forms(project, iw.evaluate(project))
        result = f15.analysis(project)
        self.assertTrue(result.no_offsite_scenario)
        self.assertEqual(result.reference_grade, "다")

    def test_missing_inputs_are_reported_and_no_grade_is_invented(self):
        project = _project_with_targets()
        result = f15.analysis(project)   # 별지 제12호 반영 전
        self.assertFalse(result.scores)
        self.assertEqual(result.reference_grade, "")
        self.assertTrue(result.blockers)

    def test_page_is_wired(self):
        self.assertIn(15, __import__("ui.cap_forms_registry", fromlist=["x"]).FORM_NUMBERS)


if __name__ == "__main__":
    unittest.main()
