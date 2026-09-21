from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import unittest

from streamlit.testing.v1 import AppTest

from engine.stage2 import cap_chemical_upload as up
from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2 import cap_judgement as jd
from engine.stage2 import cap_start
from tests.test_cap_judgement import BUSINESS
from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests

ROOT = Path(__file__).resolve().parents[1]


def _pending():
    project = CAPForm1EngineTests()._project()
    project.stage1_snapshot["business"] = dict(BUSINESS)
    project.stage1_snapshot[jd.PENDING_KEY] = True
    project.scope_confirmed = False
    project.cap_required = project.psm_required = None
    return project


class BusinessTests(unittest.TestCase):
    def test_info_is_read_from_the_same_place_the_judgement_reads(self):
        info = jd.business_info(_pending())
        self.assertEqual(info["사업장명"], BUSINESS["사업장명"])
        self.assertEqual(info["업종 또는 주요 생산품"], BUSINESS["업종 또는 주요 생산품"])

    def test_saving_updates_the_judgement_input_the_project_name_and_the_form12_fields(self):
        project = _pending()
        jd.save_business(project, "새이름공장", "울산광역시 북구 1", "정밀화학 제조")
        intake, _ = jd.build_intake(project)
        self.assertEqual(intake.business["사업장명"], "새이름공장")
        self.assertEqual(intake.business["사업장 주소"], "울산광역시 북구 1")
        self.assertEqual(project.company_name, "새이름공장")
        self.assertEqual(project.get_field("business.address").value, "울산광역시 북구 1")
        self.assertEqual(project.get_field("business.main_products").value, "정밀화학 제조")  # 별지 제12호 주요 생산품

    def test_a_blank_field_never_erases_an_existing_value(self):
        project = _pending()
        before = jd.business_info(project)
        jd.save_business(project, "", "", "")
        self.assertEqual(jd.business_info(project), before)

    def test_a_new_site_already_carries_the_industry_into_the_form12_field(self):
        outcome = cap_start.start(dict(BUSINESS), [{"제품명": "염소", "CAS No.": "7782-50-5", "최대 제조·사용량": None,
                                                     "최대 저장량": None, "단위": "kg"}])
        self.assertEqual(outcome.project.get_field("business.main_products").value, BUSINESS["업종 또는 주요 생산품"])


class UploadTests(unittest.TestCase):
    def _xlsx(self):
        from io import BytesIO

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["제품명", "CAS No.", "최대 제조·사용량", "최대 저장량", "단위"])
        ws.append(["톨루엔", "108-88-3", 500, 2000, "kg"])
        out = BytesIO()
        wb.save(out)
        return out.getvalue()

    def test_an_uploaded_list_is_added_to_the_selected_project_and_seen_by_the_judgement(self):
        project = _pending()
        before = len(chem._rows(project)[1])
        parsed = up.parse(self._xlsx(), "물질.xlsx")
        rows = up.normalize(parsed, parsed.mapping)
        added, skipped = up.add_to_project(project, rows, file_name="물질.xlsx", sha256="abc123456789")
        self.assertEqual((added, skipped), (1, 0))
        names = [r.get("제품명") for r in chem._rows(project)[1]]
        self.assertEqual(len(names), before + 1)
        self.assertIn("톨루엔", names)
        intake, _ = jd.build_intake(project)
        self.assertIn("108-88-3", list(intake.chemicals["CAS No."]))
        row = [r for r in chem._rows(project)[1] if r.get("제품명") == "톨루엔"][0]
        self.assertAlmostEqual(float(row["최대 저장량"]), 2.0)  # 2000 kg → 2 ton

    def test_the_same_file_twice_does_not_duplicate(self):
        project = _pending()
        parsed = up.parse(self._xlsx(), "물질.xlsx")
        rows = up.normalize(parsed, parsed.mapping)
        up.add_to_project(project, rows, file_name="a.xlsx", sha256="abc123456789")
        added, skipped = up.add_to_project(project, rows, file_name="a.xlsx", sha256="abc123456789")
        self.assertEqual((added, skipped), (0, 1))


class ScreenTests(unittest.TestCase):
    def _run(self, project):
        rows = [{"project_id": project.project_id, "company_name": project.company_name}]
        patches = [patch("engine.stage2.storage.list_projects", return_value=rows),
                   patch("engine.stage2.storage.load_project", return_value=project),
                   patch("engine.stage2.storage.save_project"),
                   patch("streamlit.page_link"),
                   patch("ui.cap_start_panel._gate_hold", return_value=False)]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        at = AppTest.from_file(str(ROOT / "ui/judgement_page.py"), default_timeout=90)
        at.session_state["_stage2_active_project_id"] = project.project_id
        return at.run()

    def test_the_selected_projects_business_info_is_shown_and_can_be_saved(self):
        project = _pending()
        at = self._run(project)
        self.assertFalse(at.exception)
        pid = project.project_id
        self.assertEqual(at.text_input(key=f"judge_biz_name_{pid}").value, BUSINESS["사업장명"])
        self.assertEqual(at.text_input(key=f"judge_biz_address_{pid}").value, BUSINESS["사업장 주소"])
        self.assertEqual(at.text_input(key=f"judge_biz_industry_{pid}").value, BUSINESS["업종 또는 주요 생산품"])
        at.text_input(key=f"judge_biz_name_{pid}").set_value("고친이름")
        at.button(key=f"judge_biz_save_{pid}").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(project.company_name, "고친이름")
        self.assertTrue(any("사업장 정보를 저장했습니다" in s.value for s in at.success))

    def test_a_chemical_upload_area_is_offered_for_the_selected_project(self):
        project = _pending()
        at = self._run(project)
        labels = [e.label for e in at.expander]
        self.assertTrue(any(label.startswith("물질 목록 —") for label in labels))
        self.assertGreaterEqual(sum("엑셀·CSV로 물질 목록 올리기" in label for label in labels), 2)  # 선택한 사업장 + 새 사업장


if __name__ == "__main__":
    unittest.main()
