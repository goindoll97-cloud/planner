"""회사자료 안내와 한글 형식 샘플이 실제 접수 코드에서 동작하는지 확인한다."""
import unittest

from engine.stage2 import cap_intake_guide as guide, demo_full_company as demo
from engine.stage2 import evidence_workspace as ew
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.hwp5_binary import HWP5_MAGIC


class CapIntakeGuideTests(unittest.TestCase):
    def test_full_checklist_includes_conditional_scope_and_all_registry_entries(self):
        all_rows = guide.checklist()
        keys = {row["key"] for row in all_rows}
        self.assertEqual(len(keys), len(all_rows))
        self.assertGreaterEqual(len(keys), 35)
        self.assertTrue({row["key"] for row in guide.checklist("2군")} <= keys)
        text = guide.guidance_text()
        self.assertIn("작성수준 미확정", text)
        self.assertIn("최대보유량", text)
        self.assertIn("외부 비상대응", text)
        self.assertIn("HWPX", text)
        self.assertTrue(guide.guidance_hwpx().startswith(b"PK"))
        self.assertTrue(guide.guidance_hwp().startswith(HWP5_MAGIC))
        tables, passages = ew.read_document("요청목록.hwpx", guide.guidance_hwpx())
        self.assertTrue(any("설비" in p["text"] for p in passages))
        _, hwp_passages = ew.read_document("요청목록.hwp", guide.guidance_hwp())
        self.assertTrue(any("설비" in p["text"] for p in hwp_passages))

    def test_hwpx_company_variants_read_same_core_facts(self):
        files = demo.files()
        project = create_direct_cap_project("한글판 테스트", address="가상 주소", cap_group="")
        for name, kind in (("01_제품목록_한글판.hwpx", "material"),
                           ("02_설비대장_한글판.hwpx", "facility")):
            self.assertEqual(ew.classify_document(name, files[name]), kind)
            self.assertGreater(ew.ingest(project, name, files[name], kind), 0)
        values = {(s["entity"], s["field"]): s["chosen"]["value"]
                  for s in ew.slots(project) if s["chosen"]}
        self.assertEqual(values[("facility:TK-01", "inventory")], 37000)
        self.assertEqual(values[("material:P-01", "cas")], "108-88-3")
        hwp_project = create_direct_cap_project("HWP 5.0 시험", address="가상 주소", cap_group="")
        for name, kind in (("01_제품목록_한글판.hwp", "material"),
                           ("02_설비대장_한글판.hwp", "facility")):
            self.assertTrue(files[name].startswith(HWP5_MAGIC))
            self.assertEqual(ew.classify_document(name, files[name]), kind)
            self.assertGreater(ew.ingest(hwp_project, name, files[name], kind), 0)
        hwp_values = {(s["entity"], s["field"]): s["chosen"]["value"]
                      for s in ew.slots(hwp_project) if s["chosen"]}
        self.assertEqual(hwp_values[("facility:TK-01", "inventory")], values[("facility:TK-01", "inventory")])
        for name in ("03_사업장_일반정보_한글판.hwpx", "04_공정설명서_한글판.hwpx",
                     "09_안전관리_비상대응계획_한글판.hwpx"):
            tables, _ = ew.read_document(name, files[name])
            self.assertTrue(tables)
            self.assertTrue(ew.register_reference(project, name, files[name]))
            self.assertEqual(ew.documents(project)[-1]["fact_count"], 0)
            self.assertTrue(ew.documents(project)[-1]["needs_reading"])

    def test_invalid_hwp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "HWP 5.0"):
            ew.read_document("사양서.hwp", b"old binary")


if __name__ == "__main__":
    unittest.main()
