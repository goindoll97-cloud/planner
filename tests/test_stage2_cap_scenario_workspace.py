from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2 import cap_guideline as guide
from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import cap_workspace as ws
from engine.stage2.project import Stage2Project

ROOT = Path(__file__).resolve().parents[1]


def _project(props=None, chemical="염소"):
    project = Stage2Project(project_id="S2-SC", company_name="테스트화학", cap_required=True, scope_confirmed=True,
                            cap_selected=True, cap_group="1군")
    row = {"물질명": chemical, "CAS 번호": "7782-50-5", "함량(%)": "99"}
    row.update(props or {})
    project.set_field("inventory.chemicals", "화학물질 목록", [row], "VERIFIED")
    return project


def _facilities(project, *rows):
    saved = []
    for index, row in enumerate(rows, 1):
        base = {"설비번호": f"E-{index}", "설비명": f"설비{index}", "취급물질": "염소", "시설유형": "저장탱크", "물질성상": "액체",
                "용량": 1, "용량단위": "m3", "비중": 1.0}
        base.update(row)
        saved.append(base)
    ws.save_facility_rows(project, saved)


class PreliminaryScenarioTests(unittest.TestCase):
    def test_annex2_quantities_are_read_from_the_source_document(self):
        table = guide.preliminary_scenario_quantities()
        self.assertEqual(table[("액체", "유해성 구분 없음")], 400.0)
        self.assertEqual(table[("기체", "독성구분 3")], 100.0)

    def test_liquid_is_a_target_at_400kg_and_not_below(self):
        project = _project()
        _facilities(project, {"용량": 0.5, "비중": 0.8}, {"용량": 0.3, "비중": 0.8})  # 400 kg, 240 kg
        first, second = sc.evaluate(project)
        self.assertEqual((first.verdict, first.threshold_kg), (sc.TARGET, 400.0))
        self.assertEqual(second.verdict, sc.NOT_TARGET)

    def test_solid_uses_2000kg(self):
        project = _project()
        _facilities(project, {"물질성상": "고체", "용량": 1.5, "비중": 1.0})
        [target] = sc.evaluate(project)
        self.assertEqual((target.verdict, target.threshold_kg), (sc.NOT_TARGET, 2000.0))

    def test_gas_threshold_follows_acute_toxicity_category(self):
        project = _project({"독성구분": "구분 2"})
        _facilities(project, {"물질성상": "기체·고압가스", "직접확인 최대보유량": 6, "질량단위": "kg", "직접확인 근거": "운전조건 산정"})
        [target] = sc.evaluate(project)
        self.assertEqual((target.verdict, target.threshold_kg), (sc.TARGET, 5.0))

    def test_gas_without_toxicity_category_uses_category3_quantity(self):
        project = _project()
        _facilities(project, {"물질성상": "기체·고압가스", "직접확인 최대보유량": 50, "질량단위": "kg", "직접확인 근거": "산정"})
        [target] = sc.evaluate(project)
        self.assertEqual((target.verdict, target.threshold_kg), (sc.NOT_TARGET, 100.0))

    def test_liquefied_gas_stored_as_liquid_uses_the_gas_quantity(self):
        project = _project({"물질상태": "기체", "독성구분": "구분 1"})
        _facilities(project, {"용량": 0.01, "비중": 1.4})  # 14 kg liquid
        [target] = sc.evaluate(project)
        self.assertEqual((target.verdict, target.threshold_kg, target.state), (sc.TARGET, 5.0, "기체(액화가스)"))

    def test_tank_lorry_uses_maximum_storage_and_is_an_unloading_facility(self):
        project = _project()
        _facilities(project, {"시설유형": "탱크로리·운송차량", "용량": 10, "비중": 1.0})
        [target] = sc.evaluate(project)
        self.assertEqual((target.kind, target.verdict, target.holding_kg), (sc.LORRY_KIND, sc.TARGET, 10000.0))

    def test_multi_phase_or_missing_data_needs_confirmation_never_guessed(self):
        project = _project()
        _facilities(project, {"물질성상": "복수성상"}, {"용량": ""})
        self.assertEqual([t.verdict for t in sc.evaluate(project)], [sc.CHECK, sc.CHECK])

    def test_off_site_piping_is_not_equipment(self):
        project = _project()
        _facilities(project, {"시설유형": "사외배관"})
        self.assertEqual(sc.evaluate(project), [])

    def test_accident_types_come_from_form6_facts_and_scenarios_are_shared(self):
        project = _project({"독성구분": "구분 2", "폭발한계 하한": "1.2 %"})
        _facilities(project, {"용량": 1, "비중": 1.0})
        rows = sc.proposed_scenarios(project)
        self.assertEqual([r["사고유형"] for r in rows], [sc.TOXIC, sc.FIRE])
        self.assertEqual(rows[0]["사고시나리오명"], "E-1 염소 독성 누출")
        self.assertEqual(sc.save_scenarios(project, rows + [{"사고시나리오명": ""}]), 2)
        self.assertEqual(project.get_field(sc.SCENARIO_KEY).status, "USER_CONFIRMED")
        self.assertEqual(len(sc.saved_scenarios(project)), 2)

    def test_page_is_wired(self):
        self.assertIn('12: "별지 제12호"', (ROOT / "ui/cap_workspace_page.py").read_text(encoding="utf-8"))
        self.assertIn("사고시나리오", ws.load_form_schema(12)["title"])


if __name__ == "__main__":
    unittest.main()
