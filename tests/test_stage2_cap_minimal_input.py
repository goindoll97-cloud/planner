from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest

from docx import Document

from engine.kosha_msds import KOSHAFullMSDSResult, KOSHAMSDSSection
from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2 import cap_form3_workspace as f3
from engine.stage2.cap_baseline_docx import FORM_TABLE_INDEX, build_cap_baseline_draft
from engine.stage2.project import Stage2Project

ROOT = Path(__file__).resolve().parents[1]


def _project(rows=None, **kwargs) -> Stage2Project:
    project = Stage2Project(
        project_id="S2-MIN", company_name="테스트화학", site_name="테스트공장", cap_required=True,
        cap_group="2군", scope_confirmed=True, cap_selected=True, **kwargs,
    )
    project.set_field(
        "inventory.chemicals", "화학물질 목록",
        rows if rows is not None else [{"물질명": "톨루엔", "CAS 번호": "108-88-3", "함량(%)": "99.5"}],
        "VERIFIED",
    )
    return project


def _kosha(cas: str) -> KOSHAFullMSDSResult:
    sections = {
        9: KOSHAMSDSSection(9, "물리화학적 특성", (("물리적 상태", "액체"), ("비중", "0.87"), ("폭발한계 하한", "1.2 %")), ""),
        8: KOSHAMSDSSection(8, "노출방지", (("노출기준", "TWA : 10 ppm"),), ""),
    }
    return KOSHAFullMSDSResult("REFERENCE_READY", cas, "ok", chem_id="T1", chemical_name="톨루엔",
                               sections=sections, checked_at_utc="2026-09-19T00:00:00+00:00")


class KOSHAAutoFillTests(unittest.TestCase):
    def test_mixtures_are_never_looked_up(self):
        project = _project([
            {"물질명": "톨루엔", "CAS 번호": "108-88-3"},
            {"물질명": "혼합제품", "CAS 번호": "108-88-3, 67-64-1"},
            {"물질명": "아세톤 혼합물", "CAS 번호": "67-64-1", "물질구분": "혼합물"},
        ])
        self.assertEqual(chem.single_substance_cas(project), ["108-88-3"])

    def test_lookup_only_sends_single_cas_and_gives_candidates(self):
        project = _project()
        seen = []

        def lookup(cas):
            seen.append(cas)
            return _kosha(cas)

        chem.fetch_references(project, lookup=lookup)
        self.assertEqual(seen, ["108-88-3"])
        found = {c.field: c.value for c in chem.candidates(project)}
        self.assertEqual(found["물질상태"], "액체")
        self.assertEqual(found["비중"], "0.87")
        self.assertIn("10 ppm", found["허용농도값"])

    def test_nothing_is_written_until_the_user_accepts(self):
        project = _project()
        chem.fetch_references(project, lookup=_kosha)
        _, before = chem._rows(project)
        self.assertNotIn("물질상태", before[0])

    def test_accepting_fills_only_empty_cells_and_reaches_form6(self):
        project = _project([{"물질명": "톨루엔", "CAS 번호": "108-88-3", "함량(%)": "99.5", "비중": "0.866"}])
        chem.fetch_references(project, lookup=_kosha)
        written = chem.apply_candidates(project, ["108-88-3"])
        self.assertGreater(written, 0)
        record = project.get_field("cap.chemical.details")
        self.assertEqual(record.status, "USER_CONFIRMED")
        row = record.value[0]
        self.assertEqual(row["비중"], "0.866")  # company value is never overwritten
        self.assertEqual(row["물질상태"], "액체")
        self.assertEqual(row["폭발한계 하한"], "1.2 %")
        table = Document(BytesIO(build_cap_baseline_draft(project))).tables[FORM_TABLE_INDEX["6"][0]]
        text = "\n".join(cell.text for r in table.rows for cell in r.cells)
        self.assertIn("액체", text)


class Form3SuggestionTests(unittest.TestCase):
    def _item(self, field_id):
        return next(item for item in f3.fields() if item["id"] == field_id)

    def test_intake_facts_under_other_keys_are_suggested(self):
        project = _project()
        project.set_field("business.representative", "대표자 성명", "김대표", "VERIFIED")
        self.assertEqual(f3.suggestion(project, self._item("representative")), ("김대표", "회사 자료 입력값"))

    def test_yes_no_intake_answers_map_to_printed_options(self):
        project = _project()
        project.set_field("cap.business.joint_emergency_plan", "공동", "N", "VERIFIED")
        project.set_field("cap.business.recent_accident", "사고", "Y", "VERIFIED")
        self.assertEqual(f3.suggestion(project, self._item("joint"))[0], "단독제출")
        self.assertEqual(f3.suggestion(project, self._item("recent_accident"))[0], "있음")

    def test_no_psm_suggests_similar_system_not_applicable(self):
        project = _project(psm_required=False)
        self.assertEqual(f3.suggestion(project, self._item("other_review"))[0], "미해당")

    def test_confirmed_values_are_not_re_suggested(self):
        project = _project()
        f3.save_fields(project, {"representative": "박대표"})
        self.assertEqual(f3.suggestion(project, self._item("representative")), ("", ""))

    def test_pages_use_the_helpers(self):
        page = (ROOT / "ui/cap_workspace_page.py").read_text(encoding="utf-8")
        self.assertIn("chem_ws.apply_candidates", page)
        self.assertIn("f3.suggestion", (ROOT / "ui/cap_form3_view.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
