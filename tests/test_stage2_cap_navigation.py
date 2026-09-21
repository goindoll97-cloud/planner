from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from ui import cap_forms_registry as registry
from ui import cap_frames

ROOT = Path(__file__).resolve().parents[1]


class CAPNavigationTests(unittest.TestCase):
    def test_every_registered_form_has_a_view_with_render(self):
        for number in registry.FORM_NUMBERS:
            if number == 1:
                continue  # 별지 제1호는 작성 화면 본문에 있다
            source = (ROOT / f"ui/cap_form{number}_view.py").read_text(encoding="utf-8")
            self.assertIn("def render(project)", source, number)
        self.assertEqual(registry.label(12), "별지 제12·13호")
        self.assertEqual(registry.label(3), "별지 제3호")
        self.assertNotIn(13, registry.FORM_NUMBERS)
        page = (ROOT / "ui/cap_workspace_page.py").read_text(encoding="utf-8")
        self.assertIn('"implementation": "이행점검 · 자체점검 별지 제1호~제3호"', page)
        self.assertTrue((ROOT / "ui/cap_implementation_self_check_view.py").exists())

    def test_navigation_groups_cap_psm_and_the_judgement_page(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"화학사고예방관리계획서": [', app)
        self.assertIn('st.Page("ui/cap_workspace_page.py", title="화학사고예방관리계획서 작성"', app)
        self.assertIn('sections["공정안전보고서"]', app)
        self.assertIn('st.Page("ui/judgement_page.py"', app)
        for gone in ("diagnosis_entry.py", "stage2_scope_page.py", "엑셀로 판정하기"):
            self.assertNotIn(gone, app)
        # the old Excel round-trip stages (3~5) are no longer in the menu
        for page in ("stage2_intake_page.py", "stage2_validation_page.py", "stage2_review_page.py"):
            self.assertNotIn(page, app)

    def test_big_excel_round_trip_is_gone_and_only_the_chemical_list_upload_remains(self):
        page = (ROOT / "ui/cap_workspace_page.py").read_text(encoding="utf-8")
        self.assertNotIn("cap_excel_panel", page)
        self.assertFalse((ROOT / "ui/cap_excel_panel.py").exists())
        form6 = (ROOT / "ui/cap_form6_view.py").read_text(encoding="utf-8")
        self.assertIn("chemical_upload_panel.render", form6)  # 물질 목록만 엑셀·CSV로 올린다
        start = (ROOT / "ui/cap_start_panel.py").read_text(encoding="utf-8")
        self.assertIn("chemical_upload_panel.render", start)



class ArrowSafetyTests(unittest.TestCase):
    def test_mixed_number_and_blank_columns_serialize_to_arrow(self):
        import pyarrow as pa

        frame = pd.DataFrame({"물질명": ["염소", "톨루엔"], "함량(%)": ["", 99.5], "수량": [1, 2]})
        with self.assertRaises(Exception):
            pa.Table.from_pandas(frame)  # 원래 프레임은 Arrow로 변환되지 않는다
        safe = cap_frames.safe(frame)
        table = pa.Table.from_pandas(safe)
        self.assertEqual(table.num_rows, 2)
        self.assertEqual(list(safe["함량(%)"]), ["", "99.5"])
        self.assertEqual(safe["수량"].dtype, frame["수량"].dtype)  # 숫자 열은 그대로

    def test_none_and_nan_become_empty_text(self):
        frame = pd.DataFrame({"값": [None, float("nan"), "가"]})
        self.assertEqual(list(cap_frames.safe(frame)["값"]), ["", "", "가"])


if __name__ == "__main__":
    unittest.main()
