"""회사자료 안내와 한글 형식 샘플이 실제 접수 코드에서 동작하는지 확인한다."""
import unittest
import json
import os
from io import BytesIO
from zipfile import ZipFile

from engine.stage2 import cap_intake_guide as guide, demo_full_company as demo, demo_company
from engine.stage2 import evidence_workspace as ew
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.hwp5_binary import HWP5_MAGIC


class CapIntakeGuideTests(unittest.TestCase):
    def test_plans_request_short_facts_instead_of_finished_documents(self):
        rows = {row["key"]: row for row in guide.checklist("1군")}
        expected = {"cap.external.communication": ["지역사회 소통 대상", "지역사회 소통 방법", "지역사회 소통 주기"],
                    "cap.external.mutual_aid": ["협력 기관", "협력 내용", "합동 훈련"],
                    "cap.external.evacuation": ["경보 방법", "대피 경로", "대피 장소"]}
        for key, labels in expected.items():
            row = rows[key]
            self.assertIn("작성용 정보", row["label"])
            self.assertIn("완성된 계획서는 필수가 아닙니다", row["details"])
            for label in labels:
                self.assertIn(label, row["details"])
        self.assertNotIn("cap.external.communication", {r["key"] for r in guide.checklist("2군")})

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
        groups = guide.grouped_checklist()
        self.assertEqual([name for name, _ in groups], ["1군·2군 공통", "1군만"])
        self.assertTrue(groups[0][1])
        self.assertTrue(groups[1][1])
        self.assertEqual(guide.form_zone(groups[0][1][0]), "별지 제1호")
        self.assertNotIn("[2군만]", text)
        tables, passages = ew.read_document("요청목록.hwpx", guide.guidance_hwpx())
        self.assertTrue(any("설비" in p["text"] for p in passages))
        _, hwp_passages = ew.read_document("요청목록.hwp", guide.guidance_hwp())
        self.assertTrue(any("설비" in p["text"] for p in hwp_passages))

    @unittest.skipUnless(os.environ.get("CAP_PDF_FONT_PATH"), "한국어 TTF 경로가 지정된 환경에서 검증")
    def test_pdf_contains_korean_section_labels(self):
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(guide.guidance_pdf()))
        self.assertGreaterEqual(len(reader.pages), 2)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("1군·2군 공통", text)
        self.assertNotIn("2군만", text)

    def test_combined_company_is_one_zip_with_one_answer_key(self):
        with ZipFile(BytesIO(demo_company.combined_demo_zip())) as z:
            names = z.namelist()
            self.assertEqual(len(names), len(demo_company.files()) + len(demo.stress_files()) + 2)
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(names.count("README.txt"), 1)
            self.assertEqual(names.count("answer_key.json"), 1)
            truth = json.loads(z.read("answer_key.json"))
            self.assertEqual(truth["company"], demo_company.COMPANY)
            self.assertEqual(len(truth["additional_cases"]["components"]), 2)
            self.assertIn("08_두공장_설비대장.csv", names)
            self.assertIn("12_서술형_운전기록.docx", names)
            project = create_direct_cap_project("큰 자료 시험", address="가상 주소", cap_group="")
            for name in names:
                if not name[:2].isdigit():
                    continue
                if name[:2] in {"08", "10", "11", "12"}:
                    kind = "facility"
                elif name.startswith("09_"):
                    kind = "material"
                else:
                    kind, _ = demo_company.UPLOAD[name]
                hint = "T-02" if name.startswith("12_") else demo_company.UPLOAD.get(name, (None, ""))[1]
                ew.ingest(project, name, z.read(name), kind, hint)
            self.assertTrue(any(s["key"] == "material:MIX-01|cas" and s["status"] == "값 충돌"
                                for s in ew.slots(project)))
            self.assertTrue(any(s["key"] == "facility:T-02|inventory" and s["status"] == "값 충돌"
                                for s in ew.slots(project)))

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
            self.assertGreater(ew.documents(project)[-1]["fact_count"], 0)       # 항목·값 표를 서식 칸에 연결
            self.assertFalse(ew.documents(project)[-1]["needs_reading"])

    def test_invalid_hwp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "HWP 5.0"):
            ew.read_document("사양서.hwp", b"old binary")


if __name__ == "__main__":
    unittest.main()
