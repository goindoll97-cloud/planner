from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2 import cap_form16_workspace as f16
from engine.stage2 import cap_guideline as guide
from engine.stage2 import cap_impact_workspace as iw
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_form16_engine import build_cap_form16_data
from tests.test_stage2_cap_impact_workspace import _project_with_targets

ROOT = Path(__file__).resolve().parents[1]


def _project(group="1군"):
    project = _project_with_targets()
    project.cap_group = group
    iw.apply_to_forms(project, iw.evaluate(project))
    return project


class Form16WorkspaceTests(unittest.TestCase):
    def test_schema_follows_guideline_and_every_item_cites_a_regulation_article(self):
        self.assertTrue(ws.load_form_schema(16)["title"].endswith(guide.form_guidelines()[16].title))
        for item in f16.items():
            self.assertTrue(item["checklist"], item["id"])
            self.assertIn("제", item["law"])
        self.assertEqual(len(f16.items("internal")), 8)
        self.assertEqual(len(f16.items("external")), 5)

    def test_every_item_key_is_one_the_form16_engine_reads(self):
        project = _project()
        before = set(build_cap_form16_data(project).company_blockers)
        for item in f16.items():
            f16.save_text(project, item, f"{item['label']} 내용")
        after = set(build_cap_form16_data(project).company_blockers)
        for item in f16.items():
            self.assertFalse(any(item["label"] in blocker for blocker in after), item["label"])
        self.assertLess(len(after), len(before))

    def test_second_group_sites_may_skip_the_external_section(self):
        project = _project("2군")
        labels = f16.missing(project)
        self.assertFalse(any(item["label"] in labels for item in f16.items("external")))
        self.assertTrue(any(item["label"] in labels for item in f16.items("internal")))
        first = _project("1군")
        self.assertTrue(any(item["label"] in f16.missing(first) for item in f16.items("external")))

    def test_seeds_come_from_earlier_forms_only_when_empty(self):
        project = _project()
        notice = next(i for i in f16.items() if i["id"] == "notice")
        self.assertIn("총괄영향범위 내 보호대상", f16.seed(project, notice))
        self.assertIn("한빛초등학교", f16.seed(project, notice))
        medical = next(i for i in f16.items() if i["id"] == "medical")
        self.assertEqual(f16.seed(project, medical), "")  # 의료시설이 없으면 제안하지 않음
        contact = next(i for i in f16.items() if i["id"] == "contact")
        self.assertIn("15분", f16.seed(project, contact))
        f16.save_text(project, notice, "직접 쓴 고지 계획")
        self.assertEqual(f16.current_text(project, notice), "직접 쓴 고지 계획")

    def test_blank_text_is_not_saved(self):
        project = _project()
        item = f16.items()[0]
        self.assertFalse(f16.save_text(project, item, "   "))
        self.assertEqual(f16.current_text(project, item), "")

    def test_automatic_parts_are_pulled_from_earlier_forms(self):
        data = build_cap_form16_data(_project())
        self.assertEqual(data.business["사업장명"], "테스트화학")
        self.assertTrue(data.chemical_rows)
        self.assertEqual(data.chemical_rows[0]["유해화학물질명"], "염소")

    def test_page_is_wired(self):
        self.assertIn('16: "별지 제16호"', (ROOT / "ui/cap_workspace_page.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
