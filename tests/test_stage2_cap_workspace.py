from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

from docx import Document

from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft
from engine.stage2.cap_calc import internal_volume_m3
from tests import test_stage2_cap_form1_engine as form1_tests

ROOT = Path(__file__).resolve().parents[1]


def _project():
    return form1_tests.CAPForm1EngineTests()._project()


def _screen():
    return form1_tests.CAPForm1EngineTests._screen()


class CAPCalcTests(unittest.TestCase):
    def test_geometry_volumes(self):
        self.assertAlmostEqual(internal_volume_m3("vertical_cylinder", diameter_m=2.0, height_m=3.0), 3.14159265 * 3.0, places=5)
        self.assertAlmostEqual(internal_volume_m3("sphere", diameter_m=2.0), 4.18879, places=4)
        self.assertEqual(internal_volume_m3("box", length_m=2, width_m=3, height_m=4), 24)

    def test_unusable_inputs_return_none(self):
        self.assertIsNone(internal_volume_m3("sphere", diameter_m=0))
        self.assertIsNone(internal_volume_m3("box", length_m=1, width_m=1))
        self.assertIsNone(internal_volume_m3("unknown", diameter_m=1))


class CAPWorkspaceTests(unittest.TestCase):
    def test_schema_covers_form1_tables_and_every_column_has_help(self):
        schema = ws.load_form_schema(1)
        self.assertEqual(schema["baseline_tables"], [6, 7, 8])
        for section in schema["sections"]:
            for column in section.get("columns", []):
                self.assertTrue(column.get("help"), f"{section['id']}.{column['id']} has no help text")

    def test_facility_grid_is_seeded_from_confirmed_facilities(self):
        rows = ws.facility_editor_rows(_project())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["설비번호"], "V-301")
        self.assertEqual(rows[0]["취급물질"], "염소")
        self.assertEqual(rows[0]["용량"], 2.5)

    def _filled(self, project, **overrides):
        rows = ws.facility_editor_rows(project)
        rows[0].update({"시설유형": "저장탱크", "물질성상": "액체", "용량": 2.5, "용량단위": "m3", "비중": 1.4})
        rows[0].update(overrides)
        return rows

    def test_max_holding_is_design_capacity_times_specific_gravity(self):
        project = _project()
        [result] = ws.compute_holdings(project, self._filled(project))
        self.assertEqual(result.problem, "")
        self.assertAlmostEqual(result.ton, 3.5)
        self.assertIn("설계용량 × 비중", result.basis)

    def test_liter_capacity_is_converted(self):
        project = _project()
        [result] = ws.compute_holdings(project, self._filled(project, 용량=2500, 용량단위="L"))
        self.assertAlmostEqual(result.ton, 3.5)

    def test_excluded_facility_types_are_zero_and_left_out_of_the_form(self):
        project = _project()
        rows = self._filled(project, 시설유형="사외배관")
        [result] = ws.compute_holdings(project, rows)
        self.assertTrue(result.excluded)
        ws.save_facility_rows(project, rows)
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=_screen()):
            form = ws.resolve_form1(project)
        self.assertEqual(form.facility_rows, ())

    def test_gas_holding_is_computed_from_operating_conditions(self):
        project = _project()
        rows = self._filled(project, 물질성상="기체·고압가스", 용량=10, 용량단위="m3")
        self.assertEqual(ws.extra_fields_for(rows[0])[:3], ["운전압력(MPa)", "운전온도(℃)", "분자량"])
        [asked] = ws.compute_holdings(project, rows)
        self.assertIsNone(asked.ton)
        for label in ("운전압력", "운전온도", "분자량"):
            self.assertIn(label, asked.problem)
        rows[0].update({"운전압력(MPa)": 0.5, "운전온도(℃)": 25, "분자량": 70.9})
        [answered] = ws.compute_holdings(project, rows)
        expected = (0.5 + 0.101325) * 1e6 * 10 * 0.0709 / (8.314462618 * 298.15)  # ≈ 172 kg
        self.assertAlmostEqual(answered.ton * 1000, expected, places=3)
        self.assertIn("이상기체식", answered.basis)

    def test_direct_value_overrides_the_gas_calculation(self):
        project = _project()
        rows = self._filled(project, 물질성상="기체·고압가스", 용량=10, 용량단위="m3")
        rows[0].update({"운전압력(MPa)": 0.5, "운전온도(℃)": 25, "분자량": 70.9,
                        "직접확인 최대보유량": 800, "질량단위": "kg", "직접확인 근거": "산정서"})
        [result] = ws.compute_holdings(project, rows)
        self.assertAlmostEqual(result.ton, 0.8)

    def test_molar_mass_is_taken_from_the_chemical_list_when_present(self):
        project = _project()
        chemicals = project.get_field("inventory.chemicals").value
        chemicals[0]["분자량"] = "70.9"
        project.set_field("inventory.chemicals", "화학물질 목록", chemicals, "VERIFIED")
        rows = self._filled(project, 물질성상="기체·고압가스", 용량=10, 용량단위="m3")
        rows[0].update({"운전압력(MPa)": 0.5, "운전온도(℃)": 25})
        [result] = ws.compute_holdings(project, rows)
        self.assertIsNotNone(result.ton)

    def test_operating_conditions_are_shared_with_form9(self):
        from engine.stage2 import cap_form9_workspace as f9

        project = _project()
        rows = self._filled(project, 물질성상="기체·고압가스", 용량=10, 용량단위="m3")
        rows[0].update({"운전압력(MPa)": 0.5, "운전온도(℃)": 25, "분자량": 70.9})
        ws.save_facility_rows(project, rows)
        [spec_row] = f9.rows(project)
        self.assertEqual((spec_row["운전압력"], spec_row["운전온도"]), ("0.5", "25"))

    def test_level_hint_reports_exemption_candidate_and_mismatch(self):
        below = [{"규정수량 비교": "하위 규정수량 미만"}]
        self.assertEqual(ws.level_hint(below)[0], "면제 후보")
        self.assertEqual(ws.level_hint([{"규정수량 비교": "하위 이상·상위 미만"}])[0], "2군")
        self.assertEqual(ws.level_hint([{"규정수량 비교": "상위 규정수량 이상"}, {"규정수량 비교": "하위 규정수량 미만"}])[0], "1군 기준 충족")
        self.assertEqual(ws.level_hint([{"규정수량 비교": ""}])[0], "판정 불가")
        self.assertIn("다르면", ws.level_hint([{"규정수량 비교": "하위 이상·상위 미만"}], "1군")[1])

    def test_reaction_process_asks_for_reference_content(self):
        row = {"시설유형": "제조·사용시설", "물질성상": "액체", "공정유형": "반응"}
        self.assertEqual(ws.extra_fields_for(row), ["공정유형", "별표4 기준함량(%)", "함량근거"])
        self.assertEqual(ws.extra_fields_for({"시설유형": "저장탱크", "물질성상": "액체"}), [])
        self.assertEqual(ws.extra_fields_for({"시설유형": "보관시설", "물질성상": "고체"}),
                         ["보관계획도 최대량", "일일최대보관량", "질량단위"])

    def test_edit_flows_to_form_tables_and_docx(self):
        project = _project()
        rows = self._filled(project, 설비명="수정된 염소탱크", 용량=4000, 용량단위="L", 비중=1.5)
        self.assertEqual(ws.save_facility_rows(project, rows), 1)
        self.assertEqual(project.get_field(ws.FACILITY_FIELD_KEY).status, "USER_CONFIRMED")

        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=_screen()):
            form = ws.resolve_form1(project)
            docx = build_cap_baseline_draft(project)

        self.assertEqual(form.facility_rows[0]["취급시설"], "수정된 염소탱크")
        self.assertEqual(form.facility_rows[0]["설계용량(m3)"], "4")
        self.assertEqual(form.facility_rows[0]["취급량(ton)"], "6")
        text = "\n".join(
            cell.text for row in Document(BytesIO(docx)).tables[6].rows for cell in row.cells
        )
        self.assertIn("수정된 염소탱크", text)

    def test_compact_editor_locks_material_name_and_labels_facility_row_actions(self):
        from pathlib import Path

        text = (Path(__file__).resolve().parents[1] / "ui" / "cap_facility_editor.py").read_text(encoding="utf-8")
        self.assertIn('"취급물질": st.column_config.TextColumn(', text)
        self.assertIn('disabled=["취급물질"]', text)
        self.assertIn('f"{name} 시설 행 추가"', text)
        self.assertIn('f"{material} 시설 {ordinal}행 삭제"', text)
        self.assertIn('num_rows="fixed"', text)
        self.assertNotIn('"취급물질": st.column_config.SelectboxColumn(', text)

    def test_compact_editor_deletes_only_duplicate_material_rows(self):
        from ui.cap_facility_editor import _without_extra_facility_row

        rows = [
            {"취급물질": "톨루엔", "시설유형": "저장탱크"},
            {"취급물질": "메탄올", "시설유형": "보관시설"},
            {"취급물질": "톨루엔", "시설유형": "제조·사용시설"},
        ]
        remaining = _without_extra_facility_row(rows, 2)
        self.assertEqual([row["취급물질"] for row in remaining], ["톨루엔", "메탄올"])
        self.assertIsNone(_without_extra_facility_row(remaining, 0))

    def test_compact_editor_delete_button_persists_removal_of_extra_facility(self):
        from streamlit.testing.v1 import AppTest

        from ui import cap_facility_editor

        project = _project()
        rows = ws.facility_editor_rows(project)
        rows.append({**rows[0], "설비번호": "V-302", "설비명": "두 번째 염소탱크"})
        ws.save_facility_rows(project, rows)

        def app():
            cap_facility_editor.render(
                project, prefix="delete_test", compact=True, focus_names=["염소"]
            )

        with patch("ui.cap_facility_editor.save_project"):
            at = AppTest.from_function(app, default_timeout=60).run()
            self.assertFalse(at.exception)
            delete_button = next(b for b in at.button if "2행 삭제" in b.label)
            delete_button.click().run()
            self.assertFalse(at.exception)

        saved = ws.facility_editor_rows(project)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["취급물질"], "염소")

    def test_judgement_compact_frame_only_contains_calculation_core_columns(self):
        from ui import cap_facility_editor

        project = _project()
        frame = cap_facility_editor.compact_core_frame(project, ["염소"])
        self.assertEqual(list(frame.columns), ["취급물질", "시설유형", "물질성상"])
        self.assertEqual(frame.iloc[0]["취급물질"], "염소")
        self.assertNotIn("단위공장·공정", frame.columns)
        self.assertNotIn("설비번호", frame.columns)
        self.assertNotIn("설비명", frame.columns)
        self.assertNotIn("용량", frame.columns)
        self.assertNotIn("비중", frame.columns)

    def test_judgement_facility_can_calculate_without_report_only_identifiers(self):
        project = _project()
        rows = [{
            "취급물질": "염소",
            "시설유형": "저장탱크",
            "물질성상": "액체",
            "용량": 2.5,
            "용량단위": "m3",
            "비중": 1.4,
            "설비번호": "",
            "설비명": "",
            "단위공장·공정": "",
        }]
        [result] = ws.compute_holdings(project, rows)
        self.assertEqual(result.problem, "")
        self.assertAlmostEqual(result.ton, 3.5)

    def test_values_saved_during_judgement_are_carried_to_full_form_for_later_identifiers(self):
        project = _project()
        rows = [{
            "취급물질": "염소",
            "시설유형": "저장탱크",
            "물질성상": "액체",
            "용량": 2.5,
            "용량단위": "m3",
            "비중": 1.4,
        }]
        self.assertEqual(ws.save_facility_rows(project, rows), 1)
        [saved] = ws.facility_editor_rows(project)
        self.assertEqual(saved["취급물질"], "염소")
        self.assertEqual(saved["시설유형"], "저장탱크")
        self.assertEqual(saved["용량"], 2.5)
        self.assertEqual(saved["비중"], 1.4)
        self.assertEqual(saved["설비번호"], "")
        self.assertEqual(saved["설비명"], "")
        self.assertEqual(saved["단위공장·공정"], "")

    def test_missing_core_answers_are_reported_per_facility(self):
        project = _project()
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=_screen()):
            form = ws.resolve_form1(project)
        self.assertEqual(len(form.needs), 1)
        self.assertTrue(form.needs[0])

    def test_blank_rows_are_not_saved(self):
        self.assertEqual(ws.save_facility_rows(_project(), [{"설비명": "", "용량": ""}]), 0)

    def test_steps_explain_the_core_terms_in_plain_language(self):
        steps = ws.steps(1)
        self.assertEqual([step["id"] for step in steps], ["scope", "chemicals", "facilities", "result"])
        terms = " ".join(item["term"] for step in steps for item in step["explain"])
        for needed in ("최대보유량이란?", "규정수량이란?", "1군의 조건"):
            self.assertIn(needed, terms)

    def test_result_sentences_are_one_line_per_substance(self):
        lines = ws.result_sentences([
            {"물질명": "염소", "사업장 내 최대보유량(ton)": "0.8", "하위규정수량(ton)": "0.5",
             "상위규정수량(ton)": "2", "규정수량 비교": "하위 이상·상위 미만"},
            {"물질명": "메탄올", "사업장 내 최대보유량(ton)": "", "하위규정수량(ton)": "", "상위규정수량(ton)": ""},
        ])
        self.assertIn("0.8톤", lines[0])
        self.assertIn("하위 이상·상위 미만", lines[0])
        self.assertIn("계산하지 못했습니다", lines[1])

    def test_kosha_result_is_only_a_candidate(self):
        from engine.kosha_msds import KOSHAMSDSResult

        fake = KOSHAMSDSResult("MATCHED", "7782-50-5", "ok", chemical_name="염소")
        with patch("engine.kosha_msds.lookup_by_cas", return_value=fake):
            found = ws.kosha_name_candidate("7782-50-5")
        self.assertEqual(found["chemical_name"], "염소")
        self.assertEqual(found["origin"], ws.ORIGIN_LOOKUP)

    def test_page_is_wired_into_navigation(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('st.Page("ui/cap_workspace_page.py"', app)
        page = (ROOT / "ui/cap_workspace_page.py").read_text(encoding="utf-8")
        self.assertIn("help=col.get(\"help\")", page)
        self.assertIn('report_export_panel.render(project, "CAP")', page)  # 규정서식 DOCX는 공용 내보내기 단계에서 만든다

class CAPSharedFactsTests(unittest.TestCase):
    """Facilities entered once in 별지 제1호 must reappear in the other 별지."""

    def _saved(self):
        project = _project()
        rows = ws.facility_editor_rows(project)
        rows[0].update({"설비번호": "TK-9", "설비명": "염소 저장탱크", "시설유형": "저장탱크",
                        "물질성상": "액체", "용량": 2.5, "용량단위": "m3", "비중": 1.4})
        rows.append({"설비번호": "LR-1", "설비명": "탱크로리", "취급물질": "염소", "시설유형": "탱크로리·운송차량"})
        ws.save_facility_rows(project, rows)
        return project

    def test_form9_lists_the_same_facilities_with_computed_holding(self):
        from engine.stage2.cap_form9_engine import build_cap_form9_data

        data = build_cap_form9_data(self._saved())
        self.assertEqual([r["구분기호"] for r in data.rows], ["TK-9"])
        self.assertEqual(data.rows[0]["설계용량(m3)"], "2.5")
        self.assertEqual(data.rows[0]["취급량(ton)"], "3.5")

    def test_form4_5_facility_type_counts_follow_the_grid(self):
        from engine.stage2.cap_final_form_runtime import render_facility_type_counts

        text = render_facility_type_counts(self._saved())
        self.assertIn("☒ 저장탱크 (1)기", text)

    def test_unsaved_project_still_uses_legacy_facility_keys(self):
        from engine.stage2.cap_shared_facts import workspace_facility_rows

        self.assertEqual(workspace_facility_rows(_project()), [])


class GravityCandidateTests(unittest.TestCase):
    def _project_with_properties(self):
        from engine.stage2 import cap_chemical_workspace as chem

        project = _project()
        project.set_field(
            chem.DETAILS_KEY, "화학물질 목록",
            [
                {"물질명": "염소", "CAS 번호": "7782-50-5", "함량(%)": 99.9, "비중": "1.4"},
                {"물질명": "톨루엔", "CAS 번호": "108-88-3", "함량(%)": 99.5, "비중": ""},
            ],
            "USER_CONFIRMED",
        )
        return project

    def test_candidates_only_include_rows_with_a_numeric_gravity(self):
        candidates = ws.gravity_candidates(self._project_with_properties())
        self.assertEqual(candidates, [{"물질명": "염소", "CAS 번호": "7782-50-5", "비중": 1.4}])

    def test_exact_name_match_is_preferred_over_partial(self):
        candidates = [
            {"물질명": "염소", "CAS 번호": "7782-50-5", "비중": 1.4},
            {"물질명": "무수 톨루엔", "CAS 번호": "", "비중": 0.87},
        ]
        exact = ws.gravity_matches_for({"취급물질": "염소"}, candidates)
        self.assertEqual(exact, [{"물질명": "염소", "CAS 번호": "7782-50-5", "비중": 1.4}])
        # 정확히 같은 이름이 없으면 부분적으로 겹치는 이름까지 넓힌다(짧은 약칭으로 적은 경우 등).
        partial = ws.gravity_matches_for({"취급물질": "무수 톨루엔 보관"}, candidates)
        self.assertEqual(partial, [{"물질명": "무수 톨루엔", "CAS 번호": "", "비중": 0.87}])

    def test_no_match_when_facility_substance_is_blank_or_unrelated(self):
        candidates = ws.gravity_candidates(self._project_with_properties())
        self.assertEqual(ws.gravity_matches_for({"취급물질": ""}, candidates), [])
        self.assertEqual(ws.gravity_matches_for({"취급물질": "황산"}, candidates), [])


class GravityFacilityEditorTests(unittest.TestCase):
    def test_picking_a_candidate_overwrites_the_gravity_cell(self):
        from streamlit.testing.v1 import AppTest

        from engine.stage2 import cap_chemical_workspace as chem

        project = _project()
        project.set_field(
            chem.DETAILS_KEY, "화학물질 목록",
            [{"물질명": "염소", "CAS 번호": "7782-50-5", "함량(%)": 99.9, "비중": "1.4"}],
            "USER_CONFIRMED",
        )
        rows = ws.facility_editor_rows(project)
        rows[0]["취급물질"] = "염소"
        rows[0]["비중"] = ""
        ws.save_facility_rows(project, rows)  # sets project.fields in memory; no disk needed

        def app():
            import streamlit as st

            from engine.stage2.storage import load_project
            from ui import cap_facility_editor

            cap_facility_editor.render(load_project(st.session_state["_gravity_test_project_id"]), prefix="test")

        # ui.cap_facility_editor imported `save_project` by name at module load time
        # (possibly from an earlier, unrelated test's AppTest run in this same
        # process), so patching engine.stage2.storage.save_project would not reach
        # it; patch the name where it is actually looked up. load_project is
        # imported fresh inside app() on every rerun, so patching it on the
        # storage module works. Real disk I/O (and the cross-test path/tempdir
        # races that come with it) is avoided entirely.
        with patch("engine.stage2.storage.load_project", return_value=project), \
             patch("ui.cap_facility_editor.save_project"):
            at = AppTest.from_function(app, default_timeout=60)
            at.session_state["_gravity_test_project_id"] = project.project_id
            at.run()
            self.assertFalse(at.exception)
            gravity_select = next(s for s in at.selectbox if s.key.startswith("test_gravity_"))
            self.assertEqual(gravity_select.options, ["직접 입력", "1.4 (염소)"])
            gravity_select.select("1.4 (염소)").run()
            at.button(key=f"test_save_{project.project_id}").click().run()
            self.assertFalse(at.exception)

        saved = ws.facility_editor_rows(project)
        self.assertEqual(str(saved[0]["비중"]), "1.4")


if __name__ == "__main__":
    unittest.main()
