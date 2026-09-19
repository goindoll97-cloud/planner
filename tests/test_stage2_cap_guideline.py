from __future__ import annotations

import json
from pathlib import Path
import unittest

from engine.stage2 import cap_guideline as guide
from engine.stage2 import cap_workspace as ws

ROOT = Path(__file__).resolve().parents[1]


class CAPGuidelineTests(unittest.TestCase):
    def test_all_sixteen_forms_are_read_from_the_guideline(self):
        self.assertEqual(sorted(guide.form_guidelines()), list(range(1, 17)))
        self.assertEqual(guide.form_guidelines()[14].title, "사고시나리오별 시설빈도")

    def test_annex_rules_are_read_for_learning(self):
        rules = guide.annex_rules()
        self.assertEqual(sorted(rules), [1, 2, 3, 4])
        self.assertEqual(len(rules[1]), 6)
        self.assertIn("보관구획도", rules[1][5])

    def test_form1_workspace_follows_the_guideline(self):
        form = guide.form_guidelines()[1]
        schema = ws.load_form_schema(1)
        self.assertTrue(schema["title"].endswith(form.title))
        self.assertEqual(tuple(s["title"] for s in schema["sections"]), form.headings)
        self.assertIn("어느 하나라도 1군", form.notes[0])
        self.assertIn("어느 하나라도 1군", schema["sections"][2]["help"])
        for label in ("단위공장", "유해화학물질", "CAS No.", "함량(%)", "구분기호", "취급시설", "설계용량(m3)", "취급량(ton)"):
            self.assertIn(label, form.table_header(0))

    def test_sources_are_registered(self):
        lock = json.loads((ROOT / "data/stage2/cap_authoritative_sources.json").read_text(encoding="utf-8"))
        for entry in lock["local_source_files"].values():
            self.assertTrue((ROOT / entry["path"]).exists())


if __name__ == "__main__":
    unittest.main()
